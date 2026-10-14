"""Seed: admin user + demo org + Chitipa-Au demo project + SYNTHETIC fixtures."""
from __future__ import annotations
import json
import os
from sqlalchemy import select
from .database import SessionLocal
from . import models
from .auth import hash_password
from .config import settings


def _fixture(name: str) -> str:
    here = os.path.dirname(__file__)
    return os.path.normpath(os.path.join(here, "..", "..", "..", "data", "fixtures", name))


async def seed() -> dict:
    async with SessionLocal() as db:
        res = await db.execute(select(models.User).where(
            models.User.email == settings.admin_email()))
        if res.scalar_one_or_none():
            return {"seeded": False}
        org = models.Organisation(name="Mwamba Demo Org")
        db.add(org)
        await db.flush()
        admin = models.User(email=settings.admin_email(),
                            password_hash=hash_password(settings.admin_password()),
                            role="admin", org_id=org.id)
        db.add(admin)
        await db.flush()
        # Demo account: analyst role so it can run analyses in demo projects
        # but cannot access Admin (require_role("admin") stays closed).
        # Seeded always (not only DEMO_MODE) so the live prototype has a
        # one-click "Try the demo" login; password only from env.
        demo = models.User(email=settings.demo_email(),
                           password_hash=hash_password(settings.demo_password()),
                           role="analyst", org_id=org.id)
        db.add(demo)
        await db.flush()
        aoi = {"type": "Polygon", "coordinates": [[[33.20, -9.86], [33.38, -9.86],
                                                   [33.38, -9.69], [33.20, -9.69], [33.20, -9.86]]]}
        proj = models.Project(org_id=org.id, name="Chitipa Gold — Synthetic demo (SYNTHETIC)",
                              commodity="Au", aoi_geojson=aoi, grid_m=200.0,
                              status_label="SYNTHETIC", created_by=admin.id)
        db.add(proj)
        await db.flush()
        # ingest fixture files as stored datasets (copies into storage/uploads)
        up = os.path.join(settings.MWAMBA_STORAGE_DIR, "uploads")
        os.makedirs(up, exist_ok=True)
        fixtures = [
            ("Chitipa occurrences (SYNTHETIC)", "occurrences", "chitipa_occurrences.geojson"),
            ("Chitipa structures (SYNTHETIC)", "structure", "chitipa_structures.geojson"),
            ("Chitipa lithology (SYNTHETIC)", "geology", "chitipa_lithology.geojson"),
        ]
        import shutil
        for title, kind, fn in fixtures:
            src = _fixture(fn)
            if not os.path.exists(src):
                continue
            with open(src, encoding="utf-8") as f:
                obj = json.load(f)
            dst = os.path.join(up, f"seed_{fn}")
            shutil.copyfile(src, dst)
            db.add(models.Dataset(
                org_id=org.id, project_id=proj.id, name=title, kind=kind,
                format="geojson", crs_original="EPSG:4326", status_label="SYNTHETIC",
                licence="Synthetic fixture — test/demo only, not geological data",
                source_url="", provenance={"seed": True},
                processing_history=[{"step": "seed"}],
                quality={"ok": True, "seed": True,
                         "stats": {"n_total": len(obj.get("features", []))}},
                feature_count=len(obj.get("features", [])),
                stored_path=dst, created_by=admin.id))
        # geochem CSV -> geojson
        import csv
        csv_src = _fixture("chitipa_geochem.csv")
        if os.path.exists(csv_src):
            feats = []
            with open(csv_src, newline="", encoding="utf-8") as f:
                for row in csv.DictReader(f):
                    try:
                        lon, lat = float(row["lon"]), float(row["lat"])
                    except (ValueError, KeyError):
                        continue
                    feats.append({"type": "Feature",
                                  "geometry": {"type": "Point", "coordinates": [lon, lat]},
                                  "properties": {"Au_ppb": row.get("Au_ppb"), "As_ppm": row.get("As_ppm"),
                                                 "status_label": "SYNTHETIC"}})
            obj = {"type": "FeatureCollection", "features": feats}
            dst = os.path.join(up, "seed_chitipa_geochem.geojson")
            with open(dst, "w", encoding="utf-8") as f:
                json.dump(obj, f)
            db.add(models.Dataset(
                org_id=org.id, project_id=proj.id, name="Chitipa soil geochem (SYNTHETIC)",
                kind="geochem", format="csv->geojson", crs_original="EPSG:4326",
                status_label="SYNTHETIC",
                licence="Synthetic fixture — test/demo only",
                source_url="", provenance={"seed": True},
                processing_history=[{"step": "seed-csv-to-geojson"}],
                quality={"ok": True, "seed": True, "stats": {"n_total": len(feats)}},
                feature_count=len(feats), stored_path=dst, created_by=admin.id))
        # --- real-data project (only from data/real files with manifest provenance) ---
        await _seed_real(db, org, admin, aoi)
        # --- Chilwa Alkaline Province REE pilot (no coordinates pre-loaded) ---
        await _seed_ree(db, org, admin)
        await db.commit()
        return {"seeded": True, "admin": settings.admin_email()}


async def _seed_ree(db, org, admin) -> None:
    """Chilwa Alkaline Province carbonatite-REE pilot. No occurrence coordinates
    are invented or pre-loaded: enter them via the cited-occurrence form
    (POST /ingest/cited-occurrence) with a full literature citation. Runs stay
    INSUFFICIENT EVIDENCE until radiometric/alkaline + structure groups exist,
    and validation is meaningful once >= 5 cited occurrences exist."""
    from . import schemas as _schemas
    aoi_ree = {"type": "Polygon", "coordinates": [[[35.20, -15.90], [35.85, -15.90],
                                                   [35.85, -15.00], [35.20, -15.00],
                                                   [35.20, -15.90]]]}
    try:
        _schemas.validate_aoi(aoi_ree)
    except ValueError:
        return
    proj = models.Project(org_id=org.id, name="Chilwa Alkaline Province REE Pilot (real data)",
                          commodity="REE", aoi_geojson=aoi_ree, grid_m=200.0,
                          status_label="No data", created_by=admin.id)
    db.add(proj)
    await db.flush()


def _real(name: str) -> str:
    here = os.path.dirname(__file__)
    return os.path.normpath(os.path.join(here, "..", "..", "..", "data", "real", name))


async def _seed_real(db, org, admin, aoi) -> None:
    """Real-data pilot project. SYNTHETIC fixtures stay in the demo project;
    everything here carries source + licence + retrieval date, or is absent."""
    import shutil
    manifest_path = _real("manifest.json")
    manifest = {}
    if os.path.exists(manifest_path):
        with open(manifest_path, encoding="utf-8") as f:
            manifest = {m.get("file"): m for m in json.load(f) if m.get("file")}
    proj = models.Project(org_id=org.id, name="Chitipa Gold — Real data (evidence incomplete)",
                          commodity="Au", aoi_geojson=aoi, grid_m=200.0,
                          status_label="No data", created_by=admin.id)
    db.add(proj)
    await db.flush()
    up = os.path.join(settings.MWAMBA_STORAGE_DIR, "uploads")
    os.makedirs(up, exist_ok=True)

    # Copernicus DEM crop (VERIFIED)
    dem_src = _real("chitipa_dem_30m.tif")
    if os.path.exists(dem_src):
        m = manifest.get("chitipa_dem_30m.tif", {})
        dst = os.path.join(up, "seed_chitipa_dem_30m.tif")
        shutil.copyfile(dem_src, dst)
        with open(dst, "rb") as f:
            raw = f.read()
        try:
            from .services.rasters import validate_geotiff, slope_stats_utm
            stats, quality = validate_geotiff(raw)
            try:
                stats["slope"] = slope_stats_utm(raw)
            except Exception:
                pass
        except Exception as e:
            stats, quality = {}, {"ok": False, "errors": [str(e)], "warnings": []}
        db.add(models.Dataset(
            org_id=org.id, project_id=proj.id, name="Chitipa DEM 30 m (Copernicus GLO-30 crop)",
            kind="dem", format="geotiff", crs_original="EPSG:4326",
            status_label="VERIFIED" if quality.get("ok") else "REVIEWED",
            licence="Copernicus licence (free, attribution)",
            source_url="https://copernicus-dem-30m.s3.eu-central-1.amazonaws.com/",
            provenance={"seed": True, "source": "Copernicus DEM GLO-30 (ESA)",
                        "retrieval_date": m.get("retrieval_date", "2026-10-13"),
                        "elev_min_m": m.get("elev_min_m"), "elev_max_m": m.get("elev_max_m")},
            processing_history=[{"step": "seed-crop-aoi"}],
            quality=quality, feature_count=1, stored_path=dst, created_by=admin.id))

    # USGS MRDS sweep (VERIFIED, cited; zero gold records — recorded, not hidden)
    usgs_src = _real("usgs_mrds_chitipa.geojson")
    if os.path.exists(usgs_src):
        with open(usgs_src, encoding="utf-8") as f:
            obj = json.load(f)
        dst = os.path.join(up, "seed_usgs_mrds_chitipa.geojson")
        shutil.copyfile(usgs_src, dst)
        db.add(models.Dataset(
            org_id=org.id, project_id=proj.id, name="USGS MRDS Chitipa sweep (VERIFIED)",
            kind="occurrences", format="geojson", crs_original="EPSG:4326",
            status_label="VERIFIED", licence="US public domain",
            source_url="https://mrdata.usgs.gov/mrds/search-bbox.php",
            provenance={"seed": True, "source": "USGS MRDS",
                        "retrieval_date": "2026-10-13",
                        "note": obj.get("properties", {}).get("sweep_note", "")},
            processing_history=[{"step": "seed"}],
            quality={"ok": True, "seed": True,
                     "stats": {"n_total": len(obj.get("features", []))}},
            feature_count=len(obj.get("features", [])),
            stored_path=dst, created_by=admin.id))
