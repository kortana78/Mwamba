from __future__ import annotations
import json
import os
import uuid
from fastapi import APIRouter, Depends, UploadFile, File, Form, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from ..database import get_db
from .. import models, schemas
from ..deps import current_user, guard_write, audit
from ..services.ingest_validate import ingest_geojson_bytes, ingest_csv_text, to_points_geojson
from ..config import settings

router = APIRouter(prefix="/ingest", tags=["ingest"])


def _paths() -> str:
    d = os.path.join(settings.MWAMBA_STORAGE_DIR, "uploads")
    os.makedirs(d, exist_ok=True)
    return d


@router.post("/geojson", status_code=201)
async def ingest_geojson(name: str = Form(...), kind: str = Form("occurrences"),
                         project_id: str | None = Form(None),
                         crs_original: str = Form("auto"),
                         status_label: str = Form("VERIFIED"),
                         licence: str = Form(""), source_url: str = Form(""),
                         value_field: str | None = Form(None),
                         file: UploadFile = File(...),
                         user: models.User = Depends(guard_write),
                         db: AsyncSession = Depends(get_db)):
    raw = await file.read()
    try:
        obj, quality, n = ingest_geojson_bytes(raw, kind=kind,
                                               value_field=value_field or None,
                                               crs_declared=crs_original)
    except ValueError as e:
        raise HTTPException(400, str(e))
    if not quality["ok"]:
        raise HTTPException(422, {"message": "Validation failed — fix errors and re-upload",
                                  "quality": quality})
    fn = f"{uuid.uuid4().hex}.geojson"
    path = os.path.join(_paths(), fn)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(obj, f)
    d = models.Dataset(org_id=user.org_id, project_id=project_id, name=name, kind=kind,
                       format="geojson", crs_original=crs_original.upper(),
                       status_label=status_label, licence=licence, source_url=source_url,
                       provenance={"original_filename": file.filename, "uploader": user.email},
                       processing_history=[{"step": "upload-validate", "crs_declared": crs_original.upper()}],
                       quality=quality, feature_count=n, stored_path=path, created_by=user.id)
    db.add(d)
    await db.flush()
    await audit(db, user, "dataset.import", "dataset", d.id, f"{name} ({n} feats)")
    await db.commit()
    return {"id": d.id, "quality": quality, "feature_count": n,
            "warnings": quality["warnings"]}


@router.post("/csv", status_code=201)
async def ingest_csv(name: str = Form(...), kind: str = Form("geochem"),
                     project_id: str | None = Form(None),
                     lon_field: str = Form("lon"), lat_field: str = Form("lat"),
                     value_field: str | None = Form("Au_ppb"),
                     crs_original: str = Form("auto"),
                     status_label: str = Form("VERIFIED"),
                     licence: str = Form(""), source_url: str = Form(""),
                     file: UploadFile = File(...),
                     user: models.User = Depends(guard_write),
                     db: AsyncSession = Depends(get_db)):
    text = (await file.read()).decode("utf-8", errors="replace")
    from ..services.ingest_validate import ingest_csv_text as _csv
    from ..services.ingest_validate import (looks_projected, detect_projected_crs,
                                            reproject_feature_coords)
    from ..services.ingest_validate import log_reprojection as _logr
    quality = _csv(text, lon_field=lon_field, lat_field=lat_field,
                   value_field=value_field or None)[1]
    if not quality["ok"]:
        raise HTTPException(422, {"message": "CSV validation failed", "quality": quality})
    import csv as _csvmod, io as _io
    rows = list(_csvmod.DictReader(_io.StringIO(text)))
    obj = to_points_geojson(rows, lon_field, lat_field)
    history = [{"step": "csv-to-geojson"}]
    eff_crs = "EPSG:4326"
    if crs_original.lower() == "auto":
        xs = [f["geometry"]["coordinates"][0] for f in obj["features"]]
        ys = [f["geometry"]["coordinates"][1] for f in obj["features"]]
        if xs and looks_projected(xs + ys):
            hit = detect_projected_crs(xs, ys)
            if hit is None:
                raise HTTPException(400, "Coordinate columns look projected (metre range) but fall "
                                         "outside Malawi UTM36S for EPSG:32736/20936. Declare crs_original.")
            obj = reproject_feature_coords(obj, hit)
            eff_crs = hit
            history.append({"step": "reproject", "from_crs": hit, "to_crs": "EPSG:4326"})
    elif crs_original.upper() != "EPSG:4326":
        obj = reproject_feature_coords(obj, crs_original.upper())
        eff_crs = crs_original.upper()
        history.append({"step": "reproject", "from_crs": eff_crs, "to_crs": "EPSG:4326"})
    fn = f"{uuid.uuid4().hex}.geojson"
    path = os.path.join(_paths(), fn)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(obj, f)
    d = models.Dataset(org_id=user.org_id, project_id=project_id, name=name, kind=kind,
                       format="csv->geojson", crs_original=eff_crs,
                       status_label=status_label, licence=licence, source_url=source_url,
                       provenance={"original_filename": file.filename, "uploader": user.email,
                                   "lon_field": lon_field, "lat_field": lat_field},
                       processing_history=history,
                       quality=quality, feature_count=len(obj["features"]),
                       stored_path=path, created_by=user.id)
    db.add(d)
    await db.flush()
    await audit(db, user, "dataset.import", "dataset", d.id, f"{name} ({len(obj['features'])} rows)")
    await db.commit()
    return {"id": d.id, "quality": quality, "feature_count": len(obj["features"])}


@router.post("/validate-only")
async def validate_only(file: UploadFile = File(...),
                        user: models.User = Depends(current_user)):
    raw = await file.read()
    name = (file.filename or "").lower()
    try:
        if name.endswith(".csv"):
            _, quality = ingest_csv_text(raw.decode("utf-8", errors="replace"))
        else:
            _, quality, _ = ingest_geojson_bytes(raw, kind="occurrences", crs_declared="auto")
    except ValueError as e:
        raise HTTPException(400, str(e))
    return {"quality": quality}


def _store_fc(db, user, obj: dict, quality: dict, *, name: str, kind: str,
              project_id: str | None, filename: str, crs: str,
              licence: str, source_url: str, extra_history: list | None = None,
              status_label: str = "VERIFIED", restricted: bool = False,
              provenance_extra: dict | None = None):
    import json as _json
    import uuid as _uuid
    fn = f"{_uuid.uuid4().hex}.geojson"
    path = os.path.join(_paths(), fn)
    with open(path, "w", encoding="utf-8") as f:
        _json.dump(obj, f)
    hist = [{"step": "upload-validate", "crs_declared": crs,
             "original_filename": filename}]
    hist += list(quality.get("processing_history", []))
    if extra_history:
        hist += extra_history
    prov = {"original_filename": filename, "uploader": user.email}
    if restricted:
        prov["restricted"] = True
        prov["redistribution"] = "none — local use only (e.g. WDPA licence)"
    if provenance_extra:
        prov.update(provenance_extra)
    lic = licence or ("No redistribution — local use only" if restricted else "")
    d = models.Dataset(org_id=user.org_id, project_id=project_id, name=name, kind=kind,
                       format="geojson", crs_original=quality.get("crs_detected", crs),
                       status_label=status_label, licence=lic, source_url=source_url,
                       provenance=prov,
                       processing_history=hist, quality=quality,
                       feature_count=len(obj.get("features", [])),
                       stored_path=path, created_by=user.id)
    return d, path


@router.post("/shapefile", status_code=201)
async def ingest_shapefile(name: str = Form(...), kind: str = Form("geology"),
                           project_id: str | None = Form(None),
                           crs_original: str = Form("auto"),
                           licence: str = Form(""), source_url: str = Form(""),
                           restricted: bool = Form(False),
                           file: UploadFile = File(...),
                           user: models.User = Depends(guard_write),
                           db: AsyncSession = Depends(get_db)):
    """Zipped shapefile (.zip with one .shp layer). CRS: 'auto' tests Malawi
    UTM36S frames, or declare EPSG:xxxx. .prj is reported, not trusted blindly.
    restricted=true (e.g. WDPA) marks local-only: excluded from git + exports."""
    from ..services.vectorfiles import read_zipped_shapefile
    from ..services.ingest_validate import ingest_geojson_bytes as _gj
    import json as _json
    raw = await file.read()
    try:
        obj, info = read_zipped_shapefile(raw)
    except ValueError as e:
        raise HTTPException(400, str(e))
    if info.get("prj_present") and crs_original == "auto":
        pass  # still test envelope; .prj text is unreliable for Arc1950 vs WGS84
    try:
        obj2, quality, n = _gj(_json.dumps(obj).encode(), kind=kind, crs_declared=crs_original)
    except ValueError as e:
        raise HTTPException(400, str(e))
    if not quality["ok"]:
        raise HTTPException(422, {"message": "Validation failed", "quality": quality})
    is_restricted = bool(restricted) or "wdpa" in (file.filename or "").lower()
    lic = licence or ("WDPA — no redistribution; local use only" if is_restricted else "")
    d, _ = _store_fc(db, user, obj2, quality, name=name, kind=kind, project_id=project_id,
                     filename=file.filename or "layer.zip", crs=crs_original,
                     licence=lic, source_url=source_url,
                     extra_history=[{"step": "shapefile-read", "info": info}],
                     restricted=is_restricted)
    db.add(d)
    await db.flush()
    await audit(db, user, "dataset.import", "dataset", d.id, f"{name} (shp, {n} feats)")
    await db.commit()
    return {"id": d.id, "quality": quality, "feature_count": n}


@router.post("/geopackage/layers")
async def gpkg_layers(file: UploadFile = File(...),
                      user: models.User = Depends(current_user)):
    from ..services.vectorfiles import list_gpkg_layers
    try:
        return {"layers": list_gpkg_layers(await file.read())}
    except ValueError as e:
        raise HTTPException(400, str(e))


@router.post("/geopackage", status_code=201)
async def ingest_geopackage(name: str = Form(...), kind: str = Form("geology"),
                            project_id: str | None = Form(None),
                            layer: str | None = Form(None),
                            licence: str = Form(""), source_url: str = Form(""),
                            file: UploadFile = File(...),
                            user: models.User = Depends(guard_write),
                            db: AsyncSession = Depends(get_db)):
    from ..services.vectorfiles import read_geopackage
    from ..services.ingest_validate import ingest_geojson_bytes as _gj
    import json as _json
    raw = await file.read()
    try:
        obj, info = read_geopackage(raw, layer=layer)
    except ValueError as e:
        raise HTTPException(400, str(e))
    # GPKG SRS enforced 4326 inside the reader; validate + store
    try:
        obj2, quality, n = _gj(_json.dumps(obj).encode(), kind=kind, crs_declared="EPSG:4326")
    except ValueError as e:
        raise HTTPException(400, str(e))
    if not quality["ok"]:
        raise HTTPException(422, {"message": "Validation failed", "quality": quality})
    d, _ = _store_fc(db, user, obj2, quality, name=name, kind=kind, project_id=project_id,
                     filename=file.filename or "layer.gpkg", crs="EPSG:4326",
                     licence=licence, source_url=source_url,
                     extra_history=[{"step": "geopackage-read", "info": info}])
    db.add(d)
    await db.flush()
    await audit(db, user, "dataset.import", "dataset", d.id, f"{name} (gpkg:{info['layer']}, {n} feats)")
    await db.commit()
    return {"id": d.id, "quality": quality, "feature_count": n}


@router.post("/kml", status_code=201)
async def ingest_kml(name: str = Form(...), kind: str = Form("occurrences"),
                     project_id: str | None = Form(None),
                     licence: str = Form(""), source_url: str = Form(""),
                     file: UploadFile = File(...),
                     user: models.User = Depends(guard_write),
                     db: AsyncSession = Depends(get_db)):
    from ..services.kml import kml_to_aoi
    from ..services.ingest_validate import ingest_geojson_bytes as _gj
    import json as _json
    raw = await file.read()
    try:
        poly = kml_to_aoi(raw)
    except ValueError as e:
        raise HTTPException(400, str(e))
    obj = {"type": "FeatureCollection",
           "features": [{"type": "Feature", "geometry": poly, "properties": {"name": name}}]}
    try:
        obj2, quality, n = _gj(_json.dumps(obj).encode(), kind=kind, crs_declared="EPSG:4326")
    except ValueError as e:
        raise HTTPException(400, str(e))
    if not quality["ok"]:
        raise HTTPException(422, {"message": "Validation failed", "quality": quality})
    d, _ = _store_fc(db, user, obj2, quality, name=name, kind=kind, project_id=project_id,
                     filename=file.filename or "layer.kml", crs="EPSG:4326",
                     licence=licence, source_url=source_url,
                     extra_history=[{"step": "kml-read"}])
    db.add(d)
    await db.flush()
    await audit(db, user, "dataset.import", "dataset", d.id, f"{name} (kml)")
    await db.commit()
    return {"id": d.id, "quality": quality, "feature_count": n}


@router.post("/geotiff", status_code=201)
async def ingest_geotiff(name: str = Form(...), kind: str = Form("dem"),
                         project_id: str | None = Form(None),
                         licence: str = Form(""), source_url: str = Form(""),
                         restricted: bool = Form(False),
                         file: UploadFile = File(...),
                         user: models.User = Depends(guard_write),
                         db: AsyncSession = Depends(get_db)):
    """GeoTIFF/COG upload: CRS, nodata, resolution and Malawi extent validated.
    restricted=true marks local-only (excluded from git + exports)."""
    import uuid as _uuid
    from ..services.rasters import validate_geotiff, slope_stats_utm
    if kind not in ("dem", "geophysics", "remotesensing"):
        raise HTTPException(400, f"GeoTIFF kinds: dem|geophysics|remotesensing (got {kind})")
    raw = await file.read()
    try:
        stats, quality = validate_geotiff(raw, max_mb=settings.max_upload_mb())
    except ValueError as e:
        raise HTTPException(400, str(e))
    if not quality["ok"]:
        raise HTTPException(422, {"message": "GeoTIFF validation failed", "quality": quality})
    fn = f"{_uuid.uuid4().hex}.tif"
    path = os.path.join(_paths(), fn)
    with open(path, "wb") as f:
        f.write(raw)
    if kind == "dem":
        try:
            stats["slope"] = slope_stats_utm(raw)
        except Exception:
            pass
    d = models.Dataset(org_id=user.org_id, project_id=project_id, name=name, kind=kind,
                       format="geotiff", crs_original=f"EPSG:{stats['epsg']}" if stats["epsg"] else stats["crs"],
                       status_label="VERIFIED",
                       licence=licence or ("No redistribution — local use only" if restricted else ""),
                       source_url=source_url,
                       provenance={"original_filename": file.filename, "uploader": user.email,
                                   **({"restricted": True, "redistribution": "none — local use only"}
                                      if restricted else {})},
                       processing_history=[{"step": "geotiff-validate"}],
                       quality=quality, feature_count=1,
                       stored_path=path, created_by=user.id)
    db.add(d)
    await db.flush()
    await audit(db, user, "dataset.import", "dataset", d.id, f"{name} (geotiff)")
    await db.commit()
    return {"id": d.id, "quality": quality, "stats": stats}


@router.post("/cited-occurrence", status_code=201)
async def ingest_cited_occurrence(body: schemas.CitedOccurrenceIn,
                                  user: models.User = Depends(guard_write),
                                  db: AsyncSession = Depends(get_db)):
    """Literature occurrence entry: coordinates in any supported CRS + citation.

    VERIFIED only with a full citation (author + year + title); otherwise the
    record is stored UNVERIFIED and can never silently validate a model.
    """
    from ..services.ingest_validate import reproject_feature_coords
    from ..services.ingest_validate import SUPPORTED_CRS as _SUPPORTED_CRS
    SUPPORTED_CRS = _SUPPORTED_CRS
    if body.commodity not in schemas.COMMODITIES:
        raise HTTPException(400, f"Unknown commodity {body.commodity!r}. "
                                 f"Valid: {sorted(schemas.COMMODITIES)}")
    crs = (body.crs_original or "EPSG:4326").upper()
    if crs != "EPSG:4326" and crs not in SUPPORTED_CRS:
        raise HTTPException(400, f"Unknown CRS {crs}. Supported: {sorted(SUPPORTED_CRS)}")
    if body.project_id:
        proj = await db.get(models.Project, body.project_id)
        if proj is None or proj.org_id != user.org_id:
            raise HTTPException(404, "Project not found")
    else:
        proj = None
    lon, lat = float(body.x), float(body.y)
    if crs != "EPSG:4326":
        try:
            tmp = reproject_feature_coords(
                {"type": "FeatureCollection", "features": [
                    {"type": "Feature", "geometry": {"type": "Point", "coordinates": [lon, lat]},
                     "properties": {}}]}, crs)
            lon, lat = (float(tmp["features"][0]["geometry"]["coordinates"][0]),
                        float(tmp["features"][0]["geometry"]["coordinates"][1]))
        except Exception as e:
            raise HTTPException(400, f"Cannot reproject {crs} coordinates: {e}")
    m0, n0, m1, n1 = schemas.MALAWI_BBOX
    if not (m0 <= lon <= m1 and n0 <= lat <= n1):
        raise HTTPException(400, f"Cited occurrence ({lon:.4f},{lat:.4f}) falls outside Malawi "
                                 f"{schemas.MALAWI_BBOX}. Literature records must be Malawi occurrences.")
    complete = body.citation_complete()
    status = "VERIFIED" if complete else "UNVERIFIED"
    cit_text = body.citation_text()
    obj = {"type": "FeatureCollection", "features": [
        {"type": "Feature", "geometry": {"type": "Point", "coordinates": [lon, lat]},
         "properties": {"name": body.name, "commodity": body.commodity,
                        "accuracy_m": body.accuracy_m, "citation_text": cit_text,
                        "citation": {"author": body.citation.author, "year": body.citation.year,
                                     "title": body.citation.title,
                                     "page_figure": body.citation.page_figure},
                        "notes": body.notes, "crs_original": crs}}]}
    quality = {"ok": True, "errors": [], "warnings": [] if complete else
               ["Citation incomplete (need author + year + title) — stored UNVERIFIED, "
                "excluded from VERIFIED project badges until completed."],
               "stats": {"n_total": 1, "n_valid": 1},
               "crs_detected": "EPSG:4326",
               "citation_complete": complete}
    d, _ = _store_fc(db, user, obj, quality, name=f"Cited: {body.name}", kind="occurrences",
                     project_id=body.project_id, filename="cited-occurrence-form",
                     crs=crs, licence="", source_url="",
                     extra_history=[{"step": "cited-occurrence-entry",
                                     "citation": cit_text or None}],
                     status_label=status,
                     provenance_extra={"cited": True, "citation_text": cit_text,
                                       "accuracy_m": body.accuracy_m,
                                       "citation_complete": complete})
    db.add(d)
    await db.flush()
    await audit(db, user, "dataset.cited-occurrence", "dataset", d.id,
                f"{body.name} [{status}] {cit_text[:120]}")
    await db.commit()
    return {"id": d.id, "status_label": status, "citation_complete": complete,
            "citation_text": cit_text,
            "note": ("VERIFIED cited occurrence" if complete else
                     "UNVERIFIED — add author + year + title to verify.")}


@router.post("/sentinel2", status_code=201)
async def ingest_sentinel2(name: str = Form("Sentinel-2 ratios"),
                           project_id: str | None = Form(None),
                           band_B2: int = Form(1), band_B4: int = Form(2),
                           band_B8: int = Form(3), band_B11: int = Form(4),
                           band_B12: int = Form(5),
                           licence: str = Form("Copernicus licence (free, attribution)"),
                           source_url: str = Form("https://browser.dataspace.copernicus.eu/"),
                           file: UploadFile = File(...),
                           user: models.User = Depends(guard_write),
                           db: AsyncSession = Depends(get_db)):
    """Multiband Sentinel-2 GeoTIFF -> DERIVED iron-oxide (B4/B2) + clay (B11/B12)
    + NDVI ratio grids, vegetation-masked, each registered with its recipe.

    Upload one stacked multiband file (band order declared via band_B* fields);
    separate per-band downloads can be stacked with gdal_merge.py first
    (see docs/manual-data-download.md)."""
    import uuid as _uuid
    from ..services.rasters import (validate_geotiff, sentinel2_ratios_from_multiband,
                                    write_single_band_geotiff)
    from rasterio.transform import Affine as _Affine
    raw = await file.read()
    try:
        stats, quality = validate_geotiff(raw, max_mb=settings.max_upload_mb())
    except ValueError as e:
        raise HTTPException(400, str(e))
    if not quality["ok"]:
        raise HTTPException(422, {"message": "GeoTIFF validation failed", "quality": quality})
    band_map = {"B2": band_B2, "B4": band_B4, "B8": band_B8, "B11": band_B11, "B12": band_B12}
    try:
        pack, ratio_quality = sentinel2_ratios_from_multiband(raw, band_map)
    except ValueError as e:
        raise HTTPException(400, str(e))
    arrays, meta = pack["arrays"], pack["meta"]
    tr = _Affine(*meta["transform"])
    products = [("iron_oxide", "alteration_iron_oxide", "iron-oxide B4/B2"),
                ("clay", "alteration_clay", "clay/hydroxyl B11/B12")]
    ids = []
    for arr_key, ratio_tag, recipe in products:
        tif = write_single_band_geotiff(arrays[arr_key], crs=meta["crs"], transform=tr)
        fn = f"{_uuid.uuid4().hex}.tif"
        path = os.path.join(_paths(), fn)
        with open(path, "wb") as f:
            f.write(tif)
        d = models.Dataset(
            org_id=user.org_id, project_id=project_id,
            name=f"{name} — {arr_key} (DERIVED)", kind="remotesensing",
            format="geotiff", crs_original=meta["crs"], status_label="DERIVED",
            licence=licence, source_url=source_url,
            provenance={"derived": True, "derived_ratio": ratio_tag.replace("alteration_", ""),
                        "recipe": recipe, "source_bands": band_map,
                        "veg_fraction": ratio_quality["stats"].get("veg_fraction"),
                        "original_filename": file.filename, "uploader": user.email},
            processing_history=[{"step": "sentinel2-band-math", "recipe": recipe,
                                 "veg_mask": "NDVI>0.4 masked at source"}],
            quality={"ok": True, "derived": True, "stats": ratio_quality["stats"].get(arr_key, {})},
            feature_count=1, stored_path=path, created_by=user.id)
        db.add(d)
        await db.flush()
        ids.append({"id": d.id, "ratio": ratio_tag, "name": d.name})
    await audit(db, user, "dataset.import", "dataset", ids[0]["id"] if ids else "-",
                f"{name} (sentinel2 ratios)")
    await db.commit()
    return {"datasets": ids, "stats": ratio_quality["stats"],
            "note": "DERIVED alteration proxies with recipe; vegetation-masked (NDVI>0.4)."}
