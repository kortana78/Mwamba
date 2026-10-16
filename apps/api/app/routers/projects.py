"""Projects: public reads (no login), admin-only writes.

Public responses contain only public projects; private projects are visible
solely to an admin of the same org. Dataset payloads are filtered the same
way, and uploader identities are scrubbed for anonymous readers.
"""
from __future__ import annotations
from fastapi import APIRouter, Depends, HTTPException, Query, Request, UploadFile, File
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession
from ..database import get_db
from .. import models, schemas
from ..deps import optional_user, require_admin, audit, visible_project, visible_dataset
from ..ratelimit import public_limit

router = APIRouter(prefix="/projects", tags=["projects"])


def derive_status(datasets: list, evidence_sufficient: bool | None = None) -> str:
    """Project badge derives from its datasets — never a stored claim.

    "No data" (empty) | "SYNTHETIC" (all synthetic) | "VERIFIED" (all sourced/
    reviewed AND evidence sufficient) | "EVIDENCE INCOMPLETE" (all sourced but
    the latest run lacks required evidence groups) | "MIXED" (anything else).
    A new empty project never shows VERIFIED. evidence_sufficient=None means
    "no completed run yet" — sufficiency unknown, badge falls back to labels.
    """
    if not datasets:
        return "No data"
    labels = {d.status_label for d in datasets}
    if labels == {"SYNTHETIC"}:
        return "SYNTHETIC"
    if labels <= {"VERIFIED", "REVIEWED"}:
        if evidence_sufficient is False:
            return "EVIDENCE INCOMPLETE"
        return "VERIFIED"
    if "UNVERIFIED" in labels:
        return "MIXED"
    if evidence_sufficient is False and labels <= {"VERIFIED", "REVIEWED", "DERIVED", "UNVERIFIED"}:
        return "EVIDENCE INCOMPLETE"
    return "MIXED"


async def _project_datasets(db: AsyncSession, pid: str):
    res = await db.execute(select(models.Dataset).where(models.Dataset.project_id == pid))
    return res.scalars().all()


async def _latest_gate(db: AsyncSession, pid: str) -> bool | None:
    """Sufficiency of the latest completed run, or None when no run finished."""
    res = await db.execute(select(models.AnalysisRun).where(models.AnalysisRun.project_id == pid)
                           .order_by(models.AnalysisRun.created_at.desc()))
    for r in res.scalars().all():
        if r.status != "done":
            continue
        gate = (r.metrics or {}).get("evidence_gate")
        if isinstance(gate, dict) and "sufficient" in gate:
            return bool(gate["sufficient"])
        meta = r.grid_meta or {}
        if "insufficient_evidence" in meta:
            return not bool(meta["insufficient_evidence"])
        return None
    return None


def _public_ds(d, anon: bool) -> dict:
    # Licence/source are public metadata; uploader identities are not.
    return {"id": d.id, "name": d.name, "kind": d.kind,
            "status_label": d.status_label, "feature_count": d.feature_count,
            "visibility": d.visibility or "private",
            "licence": d.licence, "source_url": d.source_url}


@router.get("")
@public_limit
async def list_projects(request: Request, limit: int = Query(50, le=200), offset: int = 0,
                        user: models.User | None = Depends(optional_user),
                        db: AsyncSession = Depends(get_db)):
    res = await db.execute(select(models.Project).order_by(models.Project.created_at.desc()))
    items = [p for p in res.scalars().all() if visible_project(p, user)]
    total = len(items)
    out = []
    for p in items[offset:offset + limit]:
        dss = [d for d in await _project_datasets(db, p.id) if visible_dataset(d, user)]
        out.append({"id": p.id, "name": p.name, "commodity": p.commodity,
                    "commodity_name": schemas.COMMODITIES.get(p.commodity, p.commodity),
                    "aoi_geojson": p.aoi_geojson, "grid_m": p.grid_m,
                    "visibility": p.visibility or "private", "is_demo": bool(p.is_demo),
                    "status_label": derive_status(dss, await _latest_gate(db, p.id)),
                    "n_datasets": len(dss)})
    return {"total": total, "items": out}


@router.post("", status_code=201)
async def create_project(body: schemas.ProjectIn, user: models.User = Depends(require_admin),
                         db: AsyncSession = Depends(get_db)):
    if body.commodity not in schemas.COMMODITIES:
        raise HTTPException(400, f"Unknown commodity {body.commodity!r}. "
                                 f"Valid: {sorted(schemas.COMMODITIES)}")
    try:
        aoi = schemas.validate_aoi(body.aoi_geojson)
    except ValueError as e:
        raise HTTPException(400, str(e))
    if not (10.0 <= float(body.grid_m) <= 5000.0):
        raise HTTPException(400, "grid_m must be 10..5000 m")
    p = models.Project(org_id=user.org_id, name=body.name, commodity=body.commodity,
                       aoi_geojson=aoi, grid_m=body.grid_m, visibility=body.visibility,
                       status_label="No data", created_by=user.id)
    db.add(p)
    await db.flush()
    await audit(db, user, "project.create", "project", p.id, p.name)
    await db.commit()
    return {"id": p.id, "name": p.name, "status_label": "No data",
            "visibility": p.visibility}


@router.get("/{pid}")
@public_limit
async def get_project(request: Request, pid: str,
                      user: models.User | None = Depends(optional_user),
                      db: AsyncSession = Depends(get_db)):
    p = await db.get(models.Project, pid)
    if p is None or not visible_project(p, user):
        raise HTTPException(404, "Project not found")
    anon = user is None
    dss = [d for d in await _project_datasets(db, pid) if visible_dataset(d, user)]
    res = await db.execute(select(models.AnalysisRun).where(models.AnalysisRun.project_id == pid)
                           .order_by(models.AnalysisRun.created_at.desc()))
    runs = res.scalars().all()
    return {"id": p.id, "name": p.name, "commodity": p.commodity,
            "commodity_name": schemas.COMMODITIES.get(p.commodity, p.commodity),
            "aoi_geojson": p.aoi_geojson, "grid_m": p.grid_m,
            "visibility": p.visibility or "private", "is_demo": bool(p.is_demo),
            "status_label": derive_status(dss, await _latest_gate(db, pid)),
            "evidence_gate": await _latest_gate(db, pid),
            "datasets": [_public_ds(d, anon) for d in dss],
            "runs": [{"id": r.id, "method": r.method, "status": r.status, "progress": r.progress,
                      "created_at": r.created_at.isoformat() if r.created_at else None} for r in runs]}


@router.patch("/{pid}")
async def patch_project(pid: str, body: schemas.ProjectPatch,
                        user: models.User = Depends(require_admin),
                        db: AsyncSession = Depends(get_db)):
    """Admin visibility toggle (public/private) + demo flag + rename."""
    p = await db.get(models.Project, pid)
    if p is None or p.org_id != user.org_id:
        raise HTTPException(404, "Project not found")
    if body.name is not None:
        p.name = body.name
    if body.visibility is not None:
        p.visibility = body.visibility
    if body.is_demo is not None:
        p.is_demo = body.is_demo
    await audit(db, user, "project.patch", "project", p.id,
                f"visibility={p.visibility} is_demo={bool(p.is_demo)}")
    await db.commit()
    return {"id": p.id, "visibility": p.visibility, "is_demo": bool(p.is_demo)}


@router.post("/parse-aoi")
async def parse_aoi(file: UploadFile = File(...),
                    user: models.User = Depends(require_admin)):
    """Upload GeoJSON/KML AOI -> normalised Polygon + validation. Used by the
    project wizard's Upload tab (paste-GeoJSON stays client-side)."""
    raw = await file.read()
    name = (file.filename or "").lower()
    try:
        if name.endswith((".geojson", ".json")):
            import json as _json
            aoi = schemas.validate_aoi(_json.loads(raw.decode("utf-8")))
        elif name.endswith((".kml", ".xml")):
            from ..services.kml import kml_to_aoi
            aoi = schemas.validate_aoi(kml_to_aoi(raw))
        else:
            raise HTTPException(400, "AOI upload accepts .geojson or .kml")
    except ValueError as e:
        raise HTTPException(400, str(e))
    return {"aoi_geojson": aoi, "note": "AOI validated inside Malawi."}
