from __future__ import annotations
import base64
import io
import os
import numpy as np
from fastapi import APIRouter, Depends, HTTPException, BackgroundTasks, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from ..database import get_db
from .. import models, schemas
from ..deps import current_user, guard_write, audit
from ..worker import launch_run

router = APIRouter(prefix="/runs", tags=["runs"])


@router.post("", status_code=201)
async def create_run(project_id: str, body: schemas.RunIn,
                     background: BackgroundTasks,
                     user: models.User = Depends(guard_write),
                     db: AsyncSession = Depends(get_db)):
    p = await db.get(models.Project, project_id)
    if p is None or p.org_id != user.org_id:
        raise HTTPException(404, "Project not found")
    if body.method in ("wofe", "logreg"):
        pass  # gated inside engine with honest message; allow queueing
    run = models.AnalysisRun(project_id=project_id, method=body.method,
                             config=body.config, seed=body.seed,
                             dataset_ids=body.dataset_ids or [],
                             status="queued", progress=0.0, created_by=user.id)
    # stamp holdout fraction into config
    cfg = dict(body.config or {})
    cfg.setdefault("holdout_fraction", body.holdout_fraction)
    cfg.setdefault("grid_m", p.grid_m)
    run.config = cfg
    db.add(run)
    await db.flush()
    await audit(db, user, "run.create", "run", run.id, f"method={body.method}")
    await db.commit()
    launch_run(run.id, background)
    return {"id": run.id, "status": "queued"}


@router.get("")
async def list_runs(project_id: str | None = None,
                    user: models.User = Depends(current_user),
                    db: AsyncSession = Depends(get_db)):
    q = select(models.AnalysisRun).order_by(models.AnalysisRun.created_at.desc())
    runs = (await db.execute(q)).scalars().all()
    if project_id:
        runs = [r for r in runs if r.project_id == project_id]
    # org scoping via project
    out = []
    for r in runs:
        p = await db.get(models.Project, r.project_id)
        if p is None or p.org_id != user.org_id:
            continue
        out.append({"id": r.id, "project_id": r.project_id, "method": r.method,
                    "status": r.status, "progress": r.progress, "error": r.error[:500],
                    "grid_meta": r.grid_meta, "metrics": r.metrics,
                    "created_at": r.created_at.isoformat() if r.created_at else None})
    return {"total": len(out), "items": out}


@router.get("/{rid}")
async def get_run(rid: str, user: models.User = Depends(current_user),
                  db: AsyncSession = Depends(get_db)):
    r = await db.get(models.AnalysisRun, rid)
    if r is None:
        raise HTTPException(404, "Run not found")
    p = await db.get(models.Project, r.project_id)
    if p is None or p.org_id != user.org_id:
        raise HTTPException(404, "Run not found")
    return {"id": r.id, "project_id": r.project_id, "method": r.method,
            "status": r.status, "progress": r.progress, "error": r.error[:2000],
            "config": r.config, "seed": r.seed, "code_version": r.code_version,
            "grid_meta": r.grid_meta, "metrics": r.metrics, "dataset_ids": r.dataset_ids}


@router.post("/{rid}/rerun", status_code=201)
async def rerun(rid: str, background: BackgroundTasks,
                user: models.User = Depends(guard_write),
                db: AsyncSession = Depends(get_db)):
    r = await db.get(models.AnalysisRun, rid)
    if r is None:
        raise HTTPException(404, "Run not found")
    p = await db.get(models.Project, r.project_id)
    if p is None or p.org_id != user.org_id:
        raise HTTPException(404, "Run not found")
    # identical inputs => byte-identical grid (determinism acceptance test)
    run2 = models.AnalysisRun(project_id=r.project_id, method=r.method, config=r.config,
                              seed=r.seed, dataset_ids=r.dataset_ids,
                              status="queued", progress=0.0, created_by=user.id)
    db.add(run2)
    await db.flush()
    await audit(db, user, "run.rerun", "run", run2.id, f"from={rid}")
    await db.commit()
    launch_run(run2.id, background)
    return {"id": run2.id, "status": "queued", "note": "Same inputs+seed must give identical grid"}


@router.get("/{rid}/grid_points")
async def grid_points(rid: str, stride: int = Query(4, ge=1, le=20),
                      user: models.User = Depends(current_user),
                      db: AsyncSession = Depends(get_db)):
    """Sampled prospectivity grid as GeoJSON points (no TiTiler required)."""
    import json as _json
    r = await db.get(models.AnalysisRun, rid)
    if r is None:
        raise HTTPException(404, "Run not found")
    p = await db.get(models.Project, r.project_id)
    if p is None or p.org_id != user.org_id:
        raise HTTPException(404, "Run not found")
    if r.status != "done" or not r.grid_path or not os.path.exists(r.grid_path):
        return {"type": "FeatureCollection", "features": [],
                "properties": {"status": r.status, "note": "Grid not ready"}}
    score = np.load(r.grid_path)
    cov = np.load(r.coverage_path) if r.coverage_path and os.path.exists(r.coverage_path) else np.ones_like(score)
    gm = r.grid_meta or {}
    ox, oy, gm_m = float(gm.get("origin_x", 0)), float(gm.get("origin_y", 0)), float(gm.get("grid_m", 100))
    from pyproj import Transformer
    t = Transformer.from_crs("EPSG:32736", "EPSG:4326", always_xy=True)
    feats = []
    for iy in range(0, score.shape[0], stride):
        for ix in range(0, score.shape[1], stride):
            v = float(score[iy, ix])
            if not np.isfinite(v):
                continue
            x = ox + (ix + 0.5) * gm_m
            y = oy + (iy + 0.5) * gm_m
            lon, lat = t.transform(x, y)
            feats.append({"type": "Feature",
                          "geometry": {"type": "Point", "coordinates": [lon, lat]},
                          "properties": {"score": round(v, 4), "coverage": round(float(cov[iy, ix]), 3)}})
    return {"type": "FeatureCollection", "features": feats,
            "properties": {"run_id": rid, "method": r.method, "status_label": "MODEL OUTPUT",
                           "note": "Relative rankings 0..1, stride sampled"}}


@router.get("/{rid}/grid_png")
async def grid_png(rid: str, user: models.User = Depends(current_user),
                   db: AsyncSession = Depends(get_db)):
    """Prospectivity surface as PNG data-URL (viridis ramp) for map overlay."""
    r = await db.get(models.AnalysisRun, rid)
    if r is None:
        raise HTTPException(404, "Run not found")
    p = await db.get(models.Project, r.project_id)
    if p is None or p.org_id != user.org_id:
        raise HTTPException(404, "Run not found")
    if r.status != "done" or not os.path.exists(r.grid_path or ""):
        raise HTTPException(409, "Grid not ready")
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    score = np.load(r.grid_path)
    fig, ax = plt.subplots(figsize=(5, 5), dpi=100)
    ax.imshow(np.flipud(np.where(np.isfinite(score), score, np.nan)),
              cmap="viridis", vmin=0, vmax=1)
    ax.axis("off")
    buf = io.BytesIO()
    fig.savefig(buf, format="png", bbox_inches="tight", pad_inches=0)
    plt.close(fig)
    gm = r.grid_meta or {}
    return {"data_url": "data:image/png;base64," + base64.b64encode(buf.getvalue()).decode(),
            "grid_meta": gm, "status_label": "MODEL OUTPUT"}
