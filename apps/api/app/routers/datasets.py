from __future__ import annotations
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession
from ..database import get_db
from .. import models
from ..deps import current_user

router = APIRouter(prefix="/datasets", tags=["datasets"])


@router.get("")
async def list_datasets(project_id: str | None = None, kind: str | None = None,
                        limit: int = Query(50, le=200), offset: int = 0,
                        user: models.User = Depends(current_user),
                        db: AsyncSession = Depends(get_db)):
    q = select(models.Dataset).where(models.Dataset.org_id == user.org_id)
    if project_id:
        q = q.where(models.Dataset.project_id == project_id)
    if kind:
        q = q.where(models.Dataset.kind == kind)
    res = await db.execute(q.order_by(models.Dataset.created_at.desc()).limit(limit).offset(offset))
    items = res.scalars().all()
    return {"total": len(items), "items": [{
        "id": d.id, "name": d.name, "kind": d.kind, "format": d.format,
        "crs_original": d.crs_original, "status_label": d.status_label,
        "licence": d.licence, "source_url": d.source_url, "feature_count": d.feature_count,
        "restricted": bool((d.provenance or {}).get("restricted")),
        "project_id": d.project_id, "quality": d.quality,
        "provenance": d.provenance, "processing_history": d.processing_history} for d in items]}


@router.get("/{did}")
async def get_dataset(did: str, user: models.User = Depends(current_user),
                      db: AsyncSession = Depends(get_db)):
    d = await db.get(models.Dataset, did)
    if d is None or d.org_id != user.org_id:
        raise HTTPException(404, "Dataset not found")
    return {"id": d.id, "name": d.name, "kind": d.kind, "format": d.format,
            "crs_original": d.crs_original, "status_label": d.status_label,
            "licence": d.licence, "source_url": d.source_url,
            "restricted": bool((d.provenance or {}).get("restricted")),
            "provenance": d.provenance, "processing_history": d.processing_history,
            "quality": d.quality, "feature_count": d.feature_count,
            "project_id": d.project_id}


@router.get("/{did}/geojson")
async def dataset_geojson(did: str, user: models.User = Depends(current_user),
                          db: AsyncSession = Depends(get_db)):
    """Stored vectors as GeoJSON for map rendering (org-scoped)."""
    import json as _json
    import os as _os
    from fastapi.responses import Response as _Response
    d = await db.get(models.Dataset, did)
    if d is None or d.org_id != user.org_id:
        raise HTTPException(404, "Dataset not found")
    if (d.provenance or {}).get("restricted"):
        raise HTTPException(403, "Restricted dataset (e.g. WDPA licence): local use only, "
                                 "excluded from redistribution and exports.")
    if not d.stored_path or not _os.path.exists(d.stored_path):
        raise HTTPException(404, "Stored file missing")
    try:
        with open(d.stored_path, encoding="utf-8") as f:
            obj = _json.load(f)
    except Exception:
        raise HTTPException(409, "Stored file is not GeoJSON (raster/report kinds render via their own panels)")
    if isinstance(obj, dict):
        obj.setdefault("properties", {})
        obj["properties"].update({"dataset_id": d.id, "status_label": d.status_label})
    return _Response(_json.dumps(obj), media_type="application/geo+json")


@router.get("/{did}/hillshade")
async def dataset_hillshade(did: str, user: models.User = Depends(current_user),
                            db: AsyncSession = Depends(get_db)):
    """DEM rendering for the map: hillshade PNG data-URL + lon/lat bounds
    (MapLibre image source). No TiTiler required."""
    import os as _os
    d = await db.get(models.Dataset, did)
    if d is None or d.org_id != user.org_id:
        raise HTTPException(404, "Dataset not found")
    if d.kind != "dem":
        raise HTTPException(400, "Hillshade is available for DEM (kind=dem) datasets")
    if not d.stored_path or not _os.path.exists(d.stored_path):
        raise HTTPException(404, "Stored file missing")
    with open(d.stored_path, "rb") as f:
        raw = f.read()
    from ..services.rasters import hillshade_png
    try:
        data_url, bounds = hillshade_png(raw)
    except Exception as e:
        raise HTTPException(409, f"Cannot render hillshade: {e}")
    return {"data_url": data_url, "bounds": bounds, "status_label": d.status_label,
            "note": "Hillshade visualisation of a VERIFIED elevation source"}
