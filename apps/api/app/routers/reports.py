from __future__ import annotations
from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import Response
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from ..database import get_db
from .. import models
from ..deps import current_user, audit
from ..services.exports import (targets_geojson, targets_csv, targets_kml,
                                dossier_pdf_bytes, project_summary)

router = APIRouter(tags=["reports"])


async def _scoped_targets(db, user, run_id):
    r = await db.get(models.AnalysisRun, run_id)
    if r is None:
        raise HTTPException(404, "Run not found")
    p = await db.get(models.Project, r.project_id)
    if p is None or p.org_id != user.org_id:
        raise HTTPException(404, "Run not found")
    res = await db.execute(select(models.Target).where(models.Target.run_id == run_id)
                           .order_by(models.Target.rank.asc()))
    return r, p, res.scalars().all()


@router.get("/runs/{rid}/export.geojson")
async def export_geojson(rid: str, user: models.User = Depends(current_user),
                         db: AsyncSession = Depends(get_db)):
    r, p, targets = await _scoped_targets(db, user, rid)
    await audit(db, user, "export", "run", rid, "geojson")
    await db.commit()
    import json
    return Response(json.dumps(targets_geojson(targets)), media_type="application/geo+json",
                    headers={"Content-Disposition": f"attachment; filename=targets_{rid}.geojson"})


@router.get("/runs/{rid}/export.csv")
async def export_csv(rid: str, user: models.User = Depends(current_user),
                     db: AsyncSession = Depends(get_db)):
    r, p, targets = await _scoped_targets(db, user, rid)
    await audit(db, user, "export", "run", rid, "csv")
    await db.commit()
    return Response(targets_csv(targets), media_type="text/csv",
                    headers={"Content-Disposition": f"attachment; filename=targets_{rid}.csv"})


@router.get("/runs/{rid}/export.kml")
async def export_kml(rid: str, user: models.User = Depends(current_user),
                     db: AsyncSession = Depends(get_db)):
    r, p, targets = await _scoped_targets(db, user, rid)
    await audit(db, user, "export", "run", rid, "kml")
    await db.commit()
    return Response(targets_kml(targets, p.name),
                    media_type="application/vnd.google-earth.kml+xml",
                    headers={"Content-Disposition": f"attachment; filename=targets_{rid}.kml"})


@router.get("/targets/{tid}/dossier")
async def dossier_json(tid: str, user: models.User = Depends(current_user),
                       db: AsyncSession = Depends(get_db)):
    t = await db.get(models.Target, tid)
    if t is None:
        raise HTTPException(404, "Target not found")
    r = await db.get(models.AnalysisRun, t.run_id)
    p = await db.get(models.Project, r.project_id) if r else None
    if r is None or p is None or p.org_id != user.org_id:
        raise HTTPException(404, "Target not found")
    metrics = r.metrics or {}
    return {"id": t.id, "rank": t.rank, "area_m2": t.area_m2,
            "centroid": {"lon": t.centroid_lon, "lat": t.centroid_lat,
                         "easting": t.centroid_easting, "northing": t.centroid_northing},
            "commodity": p.commodity, "run": {"id": r.id, "method": r.method},
            "mean_score": t.mean_score, "max_score": t.max_score, "coverage": t.coverage,
            "status_label": t.status_label, "review_status": t.review_status,
            "evidence": t.evidence, "polygon_geojson": t.polygon_geojson,
            "evidence_gate": metrics.get("evidence_gate"),
            "occurrence_citations": metrics.get("occurrence_citations", {}),
            "note": "MODEL OUTPUT unless REVIEWED. Scores are relative rankings."}


@router.get("/targets/{tid}/dossier.pdf")
async def dossier_pdf(tid: str, user: models.User = Depends(current_user),
                      db: AsyncSession = Depends(get_db)):
    t = await db.get(models.Target, tid)
    if t is None:
        raise HTTPException(404, "Target not found")
    r = await db.get(models.AnalysisRun, t.run_id)
    p = await db.get(models.Project, r.project_id) if r else None
    if r is None or p is None or p.org_id != user.org_id:
        raise HTTPException(404, "Target not found")
    await audit(db, user, "export", "target", tid, "pdf dossier")
    await db.commit()
    pdf = dossier_pdf_bytes(t, r, p)
    return Response(pdf, media_type="application/pdf",
                    headers={"Content-Disposition": f"attachment; filename=dossier_{tid}.pdf"})


@router.get("/projects/{pid}/summary")
async def summary(pid: str, user: models.User = Depends(current_user),
                  db: AsyncSession = Depends(get_db)):
    p = await db.get(models.Project, pid)
    if p is None or p.org_id != user.org_id:
        raise HTTPException(404, "Project not found")
    dss = (await db.execute(select(models.Dataset).where(models.Dataset.project_id == pid))).scalars().all()
    runs = (await db.execute(select(models.AnalysisRun).where(models.AnalysisRun.project_id == pid)
                             .order_by(models.AnalysisRun.created_at.asc()))).scalars().all()
    targets = []
    if runs:
        targets = (await db.execute(select(models.Target).where(
            models.Target.run_id == runs[-1].id))).scalars().all()
    return project_summary(p, list(dss), list(runs), list(targets))
