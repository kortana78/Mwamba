from __future__ import annotations
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from ..database import get_db
from .. import models, schemas
from ..deps import current_user, audit

router = APIRouter(prefix="/targets", tags=["targets"])

REVIEW_FLOW = ["Proposed", "Under review", "Field verified", "Rejected", "Advanced"]


def _t_out(t: models.Target) -> dict:
    return {"id": t.id, "run_id": t.run_id, "rank": t.rank, "area_m2": t.area_m2,
            "centroid_lon": t.centroid_lon, "centroid_lat": t.centroid_lat,
            "centroid_easting": t.centroid_easting, "centroid_northing": t.centroid_northing,
            "mean_score": t.mean_score, "max_score": t.max_score, "coverage": t.coverage,
            "status_label": t.status_label, "review_status": t.review_status,
            "reviewer": t.reviewer, "review_notes": t.review_notes,
            "evidence": t.evidence, "polygon_geojson": t.polygon_geojson}


@router.get("")
async def list_targets(run_id: str | None = None, review_status: str | None = None,
                       limit: int = Query(100, le=500), offset: int = 0,
                       user: models.User = Depends(current_user),
                       db: AsyncSession = Depends(get_db)):
    q = select(models.Target).order_by(models.Target.rank.asc()).limit(limit).offset(offset)
    if run_id:
        q = q.where(models.Target.run_id == run_id)
    if review_status:
        q = q.where(models.Target.review_status == review_status)
    items = (await db.execute(q)).scalars().all()
    # org scoping
    out = []
    for t in items:
        r = await db.get(models.AnalysisRun, t.run_id)
        if r is None:
            continue
        p = await db.get(models.Project, r.project_id)
        if p is None or p.org_id != user.org_id:
            continue
        out.append(_t_out(t))
    return {"total": len(out), "items": out}


@router.get("/{tid}")
async def get_target(tid: str, user: models.User = Depends(current_user),
                     db: AsyncSession = Depends(get_db)):
    t = await db.get(models.Target, tid)
    if t is None:
        raise HTTPException(404, "Target not found")
    r = await db.get(models.AnalysisRun, t.run_id)
    p = await db.get(models.Project, r.project_id) if r else None
    if r is None or p is None or p.org_id != user.org_id:
        raise HTTPException(404, "Target not found")
    d = _t_out(t)
    d["run"] = {"id": r.id, "method": r.method, "config": r.config}
    d["project"] = {"id": p.id, "name": p.name, "commodity": p.commodity}
    return d


@router.patch("/{tid}/review")
async def review_target(tid: str, body: schemas.ReviewIn,
                        user: models.User = Depends(current_user),
                        db: AsyncSession = Depends(get_db)):
    if user.role not in ("admin", "geologist"):
        raise HTTPException(403, "Only Admin/Geologist can review targets")
    t = await db.get(models.Target, tid)
    if t is None:
        raise HTTPException(404, "Target not found")
    r = await db.get(models.AnalysisRun, t.run_id)
    p = await db.get(models.Project, r.project_id) if r else None
    if r is None or p is None or p.org_id != user.org_id:
        raise HTTPException(404, "Target not found")
    t.review_status = body.review_status
    t.reviewer = body.reviewer or user.email
    t.review_notes = body.review_notes
    if body.review_status in ("Field verified", "Advanced"):
        t.status_label = "REVIEWED"
    await audit(db, user, "target.review", "target", t.id,
                f"{body.review_status} by {t.reviewer}")
    await db.commit()
    return _t_out(t)
