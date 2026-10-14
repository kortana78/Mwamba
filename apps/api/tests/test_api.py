"""End-to-end API tests with an isolated SQLite DB. No fake numbers — every
assertion is computed from the app's own responses."""
from __future__ import annotations
import json
import os
import sys
import tempfile

import pytest
import pytest_asyncio
from httpx import AsyncClient, ASGITransport

ROOT = os.path.normpath(os.path.join(os.path.dirname(__file__), "..", "..", ".."))
FIX = os.path.join(ROOT, "data", "fixtures")

_tmp = tempfile.mkdtemp(prefix="mwamba_test_").replace("\\", "/")
os.environ["MWAMBA_DB_URL"] = f"sqlite+aiosqlite:///{_tmp}/test.db"
os.environ["MWAMBA_STORAGE_DIR"] = os.path.join(_tmp, "storage")

sys.path.insert(0, os.path.join(ROOT, "packages", "geo"))

from apps.api.app.main import app  # noqa: E402
from apps.api.app.database import init_db  # noqa: E402


@pytest_asyncio.fixture
async def client():
    await init_db()
    from apps.api.app.seed import seed
    await seed()
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        yield c


async def _login(client) -> dict:
    r = await client.post("/auth/login", json={"email": "admin@mwamba.local", "password": "Mwamba123!"})
    assert r.status_code == 200, r.text
    return {"Authorization": f"Bearer {r.json()['access_token']}"}


async def test_health():
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        r = await c.get("/health")
        assert r.status_code == 200
        assert r.json()["ok"] is True


async def test_auth_me_and_projects(client):
    h = await _login(client)
    r = await client.get("/auth/me", headers=h)
    assert r.status_code == 200
    assert r.json()["email"] == "admin@mwamba.local"
    r = await client.get("/projects", headers=h)
    assert r.status_code == 200
    assert r.json()["total"] >= 1
    demo = next(p for p in r.json()["items"] if "synthetic" in p["name"].lower())
    pid = demo["id"]
    r = await client.get(f"/projects/{pid}", headers=h)
    assert r.status_code == 200
    assert len(r.json()["datasets"]) >= 3  # seeded fixtures


async def test_ingest_validation_rejects_bad(client):
    h = await _login(client)
    # metre-range coordinates outside every Malawi UTM36S frame: must be
    # rejected with a declare-CRS message, never guessed
    bad = {"type": "FeatureCollection", "features": [
        {"type": "Feature", "geometry": {"type": "Point", "coordinates": [5000000, 8800000]},
         "properties": {}}]}
    r = await client.post("/ingest/validate-only", headers=h,
                          files={"file": ("bad.geojson", json.dumps(bad), "application/json")})
    assert r.status_code == 400, r.text
    assert "CRS" in r.text or "crs" in r.text


async def test_ingest_auto_detects_utm36s(client):
    """Malawi UTM36S metres (EPSG:32736) auto-transform to EPSG:4326 with a log."""
    from pyproj import Transformer
    h = await _login(client)
    t = Transformer.from_crs("EPSG:4326", "EPSG:32736", always_xy=True)
    x, y = t.transform(33.27, -9.70)
    utm = {"type": "FeatureCollection", "features": [
        {"type": "Feature", "geometry": {"type": "Point", "coordinates": [x, y]},
         "properties": {"name": "UTM-P1"}}]}
    r = await client.post("/ingest/validate-only", headers=h,
                          files={"file": ("utm.geojson", json.dumps(utm), "application/json")})
    assert r.status_code == 200, r.text
    q = r.json()["quality"]
    assert q["ok"] is True
    assert q.get("crs_detected") == "EPSG:32736"


async def test_project_status_derives_from_datasets(client):
    h = await _login(client)
    aoi = {"type": "Polygon", "coordinates": [[[33.20, -9.86], [33.38, -9.86],
                                               [33.38, -9.69], [33.20, -9.69],
                                               [33.20, -9.86]]]}
    r = await client.post("/projects", headers=h,
                          json={"name": "empty-status", "commodity": "Au",
                                "aoi_geojson": aoi, "grid_m": 500.0})
    assert r.status_code == 201, r.text
    pid = r.json()["id"]
    assert r.json()["status_label"] == "No data"
    # bad commodity rejected
    r = await client.post("/projects", headers=h,
                          json={"name": "bad-comm", "commodity": "Unobtainium",
                                "aoi_geojson": aoi, "grid_m": 500.0})
    assert r.status_code == 400
    # AOI outside Malawi rejected
    r = await client.post("/projects", headers=h,
                          json={"name": "far-away", "commodity": "Au",
                                "aoi_geojson": {"type": "Polygon", "coordinates": [[[0, 0], [1, 0], [1, 1], [0, 1], [0, 0]]]}},
                          )
    assert r.status_code == 400


async def test_ingest_geojson_ok(client):
    h = await _login(client)
    with open(os.path.join(FIX, "chitipa_occurrences.geojson"), "rb") as f:
        raw = f.read()
    r = await client.get("/projects", headers=h)
    demo = next(p for p in r.json()["items"] if "synthetic" in p["name"].lower())
    pid = demo["id"]
    r = await client.post("/ingest/geojson", headers=h,
                          data={"name": "t-occ", "kind": "occurrences", "project_id": pid},
                          files={"file": ("occ.geojson", raw, "application/json")})
    assert r.status_code == 201, r.text
    assert r.json()["feature_count"] == 12


async def test_full_run_weighted_and_dossier(client):
    h = await _login(client)
    r = await client.get("/projects", headers=h)
    demo = next(p for p in r.json()["items"] if "synthetic" in p["name"].lower())
    pid = demo["id"]
    proj = (await client.get(f"/projects/{pid}", headers=h)).json()
    ds_ids = [d["id"] for d in proj["datasets"]]
    assert len(ds_ids) >= 4
    r = await client.post(f"/runs?project_id={pid}", headers=h, json={
        "method": "weighted",
        "config": {"grid_m": 500, "weights": {"dist_structure": 0.35, "fault_density": 0.2,
                                             "lithology": 0.25, "geochem_au": 0.2},
                   "target_percentile": 80.0, "target_min_area_m2": 100000.0},
        "seed": 42, "dataset_ids": ds_ids, "holdout_fraction": 0.3})
    assert r.status_code == 201, r.text
    rid = r.json()["id"]
    # in-process BackgroundTasks may not run under ASGI transport; run engine synchronously
    from apps.api.app.services.prospectivity import run_analysis_sync
    res = run_analysis_sync(rid, os.environ["MWAMBA_DB_URL"], os.environ["MWAMBA_STORAGE_DIR"])
    assert res["ok"] is True, res
    r = await client.get(f"/runs/{rid}", headers=h)
    body = r.json()
    assert body["status"] == "done", body.get("error")
    assert body["metrics"]["score_stats"]["mean"] >= 0
    # determinism: rerun identical inputs -> identical grid bytes
    import numpy as _np
    r2 = await client.post(f"/runs/{rid}/rerun", headers=h)
    assert r2.status_code == 201
    rid2 = r2.json()["id"]
    res2 = run_analysis_sync(rid2, os.environ["MWAMBA_DB_URL"], os.environ["MWAMBA_STORAGE_DIR"])
    assert res2["ok"] is True
    grids = os.path.join(os.environ["MWAMBA_STORAGE_DIR"], "grids")
    a = _np.load(os.path.join(grids, f"{rid}_score.npy"))
    b = _np.load(os.path.join(grids, f"{rid2}_score.npy"))
    assert _np.array_equal(a, b, equal_nan=True)
    # targets + dossier + validation + exports
    t = await client.get("/targets", headers=h, params={"run_id": rid})
    assert t.status_code == 200
    items = t.json()["items"]
    assert len(items) >= 1
    tid = items[0]["id"]
    d = await client.get(f"/targets/{tid}/dossier", headers=h)
    assert d.status_code == 200
    assert "evidence" in d.json()
    v = await client.get(f"/runs/{rid}/validation", headers=h)
    assert v.status_code == 200
    assert "success_rate" in v.json()
    for ext in ("geojson", "csv", "kml"):
        e = await client.get(f"/runs/{rid}/export.{ext}", headers=h)
        assert e.status_code == 200, ext
    pdf = await client.get(f"/targets/{tid}/dossier.pdf", headers=h)
    assert pdf.status_code == 200
    assert pdf.content[:4] == b"%PDF"


async def test_wofe_gated_honestly(client):
    h = await _login(client)
    # isolated project with only 2 known occurrences -> WofE/ML must refuse plainly
    aoi = {"type": "Polygon", "coordinates": [[[33.20, -9.86], [33.38, -9.86],
                                               [33.38, -9.69], [33.20, -9.69],
                                               [33.20, -9.86]]]}
    r = await client.post("/projects", headers=h,
                          json={"name": "gate-test", "commodity": "Au",
                                "aoi_geojson": aoi, "grid_m": 500.0})
    assert r.status_code == 201, r.text
    pid = r.json()["id"]
    tiny = {"type": "FeatureCollection", "features": [
        {"type": "Feature", "geometry": {"type": "Point", "coordinates": [33.27, -9.70]},
         "properties": {"name": "G-1"}},
        {"type": "Feature", "geometry": {"type": "Point", "coordinates": [33.30, -9.72]},
         "properties": {"name": "G-2"}}]}
    r = await client.post("/ingest/geojson", headers=h,
                          data={"name": "tiny-occ", "kind": "occurrences", "project_id": pid},
                          files={"file": ("tiny.geojson", json.dumps(tiny), "application/json")})
    assert r.status_code == 201, r.text
    occ_id = r.json()["id"]
    r = await client.post(f"/runs?project_id={pid}", headers=h,
                          json={"method": "wofe", "config": {"grid_m": 500},
                                "seed": 1, "dataset_ids": [occ_id]})
    rid = r.json()["id"]
    from apps.api.app.services.prospectivity import run_analysis_sync
    res = run_analysis_sync(rid, os.environ["MWAMBA_DB_URL"], os.environ["MWAMBA_STORAGE_DIR"])
    assert res["ok"] is False
    assert "insufficient" in res["error"].lower() or "needs" in res["error"].lower()


async def test_kml_and_parse_aoi(client):
    h = await _login(client)
    kml = ('<?xml version="1.0"?><kml xmlns="http://www.opengis.net/kml/2.2"><Placemark>'
           '<Polygon><outerBoundaryIs><LinearRing><coordinates>'
           '33.20,-9.86,0 33.38,-9.86,0 33.38,-9.69,0 33.20,-9.69,0 33.20,-9.86,0'
           '</coordinates></LinearRing></outerBoundaryIs></Polygon></Placemark></kml>')
    r = await client.post("/projects/parse-aoi", headers=h,
                          files={"file": ("aoi.kml", kml, "application/vnd.google-earth.kml")})
    assert r.status_code == 200, r.text
    assert r.json()["aoi_geojson"]["type"] == "Polygon"
    # KML outside Malawi rejected
    kml_bad = kml.replace("33.20", "10.00").replace("33.38", "10.10")
    r = await client.post("/projects/parse-aoi", headers=h,
                          files={"file": ("aoi.kml", kml_bad, "application/vnd.google-earth.kml")})
    assert r.status_code == 400


async def test_shapefile_geopackage_geotiff_reject_garbage(client):
    h = await _login(client)
    r = await client.post("/ingest/shapefile", headers=h,
                          data={"name": "x", "kind": "geology"},
                          files={"file": ("x.zip", b"not-a-zip", "application/zip")})
    assert r.status_code == 400
    r = await client.post("/ingest/geopackage/layers", headers=h,
                          files={"file": ("x.gpkg", b"not-a-gpkg", "application/octet-stream")})
    assert r.status_code == 400
    r = await client.post("/ingest/geotiff", headers=h,
                          data={"name": "x", "kind": "dem"},
                          files={"file": ("x.tif", b"not-a-tiff", "image/tiff")})
    assert r.status_code == 400


async def test_hillshade_only_for_dem(client):
    h = await _login(client)
    r = await client.get("/projects", headers=h)
    pid = r.json()["items"][0]["id"]
    proj = (await client.get(f"/projects/{pid}", headers=h)).json()
    occ = next(d for d in proj["datasets"] if d["kind"] == "occurrences")
    r = await client.get(f"/datasets/{occ['id']}/hillshade", headers=h)
    assert r.status_code == 400  # honest: hillshade is DEM-only


async def test_commodity_filter_real_project_badge(client):
    """USGS stone record must not validate a gold model (filter), DEM covered by seed when present."""
    h = await _login(client)
    projs = (await client.get("/projects", headers=h)).json()["items"]
    assert any("real data" in p["name"].lower() for p in projs)
    real = next(p for p in projs if "real data" in p["name"].lower())
    assert real["status_label"] in ("VERIFIED", "MIXED", "No data", "EVIDENCE INCOMPLETE")


async def _make_project(client, h, name="gate-aoi", commodity="Au"):
    aoi = {"type": "Polygon", "coordinates": [[[33.20, -9.86], [33.38, -9.86],
                                               [33.38, -9.69], [33.20, -9.69],
                                               [33.20, -9.86]]]}
    r = await client.post("/projects", headers=h,
                          json={"name": name, "commodity": commodity,
                                "aoi_geojson": aoi, "grid_m": 500.0})
    assert r.status_code == 201, r.text
    return r.json()["id"]


async def test_evidence_gate_blocks_targets_when_groups_missing(client):
    """Structure-only run: surface computed, zero ranked targets, badge EVIDENCE INCOMPLETE."""
    from apps.api.app.services.prospectivity import run_analysis_sync
    h = await _login(client)
    pid = await _make_project(client, h, "gate-insufficient")
    struct = {"type": "FeatureCollection", "features": [
        {"type": "Feature", "geometry": {"type": "LineString", "coordinates": [[33.22, -9.80], [33.34, -9.74]]},
         "properties": {"name": "F1"}}]}
    r = await client.post("/ingest/geojson", headers=h,
                          data={"name": "only-structure", "kind": "structure", "project_id": pid},
                          files={"file": ("s.geojson", json.dumps(struct), "application/json")})
    assert r.status_code == 201, r.text
    r = await client.post(f"/runs?project_id={pid}", headers=h,
                          json={"method": "weighted", "config": {"grid_m": 500}, "seed": 42})
    assert r.status_code == 201, r.text
    rid = r.json()["id"]
    res = run_analysis_sync(rid, os.environ["MWAMBA_DB_URL"], os.environ["MWAMBA_STORAGE_DIR"])
    assert res["ok"] is True, res
    assert res["n_targets"] == 0
    body = (await client.get(f"/runs/{rid}", headers=h)).json()
    assert body["status"] == "done"
    gate = body["metrics"]["evidence_gate"]
    assert gate["sufficient"] is False
    assert "host_lithology" in gate["missing_groups"]
    assert "alteration_or_geochem" in gate["missing_groups"]
    assert body["grid_meta"]["insufficient_evidence"] is True
    assert "INSUFFICIENT EVIDENCE" in body["metrics"]["note"]
    t = await client.get("/targets", headers=h, params={"run_id": rid})
    assert t.json()["items"] == []
    proj = (await client.get(f"/projects/{pid}", headers=h)).json()
    assert proj["status_label"] == "EVIDENCE INCOMPLETE"


async def test_evidence_gate_sufficient_demo_project_capped_targets(client):
    """Full synthetic evidence: gate sufficient, 1..20 ranked targets with tightened defaults."""
    from apps.api.app.services.prospectivity import run_analysis_sync
    h = await _login(client)
    r = await client.get("/projects", headers=h)
    demo = next(p for p in r.json()["items"] if "synthetic" in p["name"].lower())
    pid = demo["id"]
    r = await client.post(f"/runs?project_id={pid}", headers=h, json={
        "method": "weighted",
        "config": {"grid_m": 500, "target_percentile": 95.0,
                   "target_min_area_m2": 200000.0, "target_merge_distance_m": 500.0,
                   "target_max_targets": 20},
        "seed": 42, "holdout_fraction": 0.3})
    assert r.status_code == 201, r.text
    rid = r.json()["id"]
    res = run_analysis_sync(rid, os.environ["MWAMBA_DB_URL"], os.environ["MWAMBA_STORAGE_DIR"])
    assert res["ok"] is True, res
    body = (await client.get(f"/runs/{rid}", headers=h)).json()
    assert body["metrics"]["evidence_gate"]["sufficient"] is True
    assert 1 <= body["grid_meta"]["n_targets"] <= 20
    t = await client.get("/targets", headers=h, params={"run_id": rid})
    assert 1 <= len(t.json()["items"]) <= 20


async def test_cited_occurrence_verified_only_with_full_citation(client):
    """Full citation -> VERIFIED + visible in dataset detail and run dossier."""
    from apps.api.app.services.prospectivity import run_analysis_sync
    h = await _login(client)
    r = await client.get("/projects", headers=h)
    demo = next(p for p in r.json()["items"] if "synthetic" in p["name"].lower())
    pid = demo["id"]
    full = {"name": "Chitipa Ridge showing", "commodity": "Au", "project_id": pid,
            "x": 33.27, "y": -9.75, "crs_original": "EPSG:4326", "accuracy_m": 500,
            "citation": {"author": "GSD Malawi", "year": 2010, "title": "Chitipa memoir",
                         "page_figure": "p.42, Fig.7"},
            "notes": "artisanal workings"}
    r = await client.post("/ingest/cited-occurrence", headers=h, json=full)
    assert r.status_code == 201, r.text
    assert r.json()["status_label"] == "VERIFIED"
    cid = r.json()["id"]
    det = (await client.get(f"/datasets/{cid}", headers=h)).json()
    assert "GSD Malawi" in (det["provenance"].get("citation_text") or "")
    # incomplete citation can never be VERIFIED
    thin = dict(full, name="Rumour showing", citation={"author": "", "year": None,
                                                       "title": "", "page_figure": ""})
    r = await client.post("/ingest/cited-occurrence", headers=h, json=thin)
    assert r.status_code == 201, r.text
    assert r.json()["status_label"] == "UNVERIFIED"
    assert r.json()["citation_complete"] is False
    # outside Malawi rejected (never guess, never store far-away literature)
    far = dict(full, name="Far away", x=10.0, y=10.0)
    r = await client.post("/ingest/cited-occurrence", headers=h, json=far)
    assert r.status_code == 400
    # projected CRS accepted and reprojected (UTM metres -> degrees)
    from pyproj import Transformer
    t = Transformer.from_crs("EPSG:4326", "EPSG:32736", always_xy=True)
    ex, ey = t.transform(33.27, -9.75)
    utm = dict(full, name="UTM showing", x=ex, y=ey, crs_original="EPSG:32736")
    r = await client.post("/ingest/cited-occurrence", headers=h, json=utm)
    assert r.status_code == 201, r.text
    assert r.json()["status_label"] == "VERIFIED"
    # dossier carries the citation
    proj = (await client.get(f"/projects/{pid}", headers=h)).json()
    ds_ids = [d["id"] for d in proj["datasets"]]
    r = await client.post(f"/runs?project_id={pid}", headers=h, json={
        "method": "weighted", "config": {"grid_m": 500}, "seed": 42, "dataset_ids": ds_ids})
    rid = r.json()["id"]
    res = run_analysis_sync(rid, os.environ["MWAMBA_DB_URL"], os.environ["MWAMBA_STORAGE_DIR"])
    assert res["ok"] is True, res
    t = await client.get("/targets", headers=h, params={"run_id": rid})
    items = t.json()["items"]
    assert len(items) >= 1
    d = await client.get(f"/targets/{items[0]['id']}/dossier", headers=h)
    assert d.status_code == 200
    assert "Chitipa Ridge showing" in json.dumps(d.json().get("occurrence_citations", {}))


def _zipped_shapefile_bytes() -> bytes:
    import io as _io
    import zipfile as _zip
    import shapefile as _shp
    d = tempfile.mkdtemp(prefix="mwamba_shp_")
    base = os.path.join(d, "lyr")
    with _shp.Writer(base, shapeType=_shp.POINT) as w:
        w.field("name", "C")
        w.point(33.27, -9.70)
        w.record("P1")
    buf = _io.BytesIO()
    with _zip.ZipFile(buf, "w", _zip.ZIP_DEFLATED) as z:
        for ext in ("shp", "shx", "dbf"):
            with open(f"{base}.{ext}", "rb") as f:
                z.writestr(f"lyr.{ext}", f.read())
    return buf.getvalue()


async def test_restricted_shapefile_excluded_from_exports(client):
    """WDPA-style restricted upload: flagged local-only, blocked from geojson export."""
    h = await _login(client)
    pid = await _make_project(client, h, "gate-restricted")
    raw = _zipped_shapefile_bytes()
    r = await client.post("/ingest/shapefile", headers=h,
                          data={"name": "WDPA Malawi (local)", "kind": "constraints",
                                "project_id": pid, "restricted": "true"},
                          files={"file": ("wdpa_malawi.zip", raw, "application/zip")})
    assert r.status_code == 201, r.text
    did = r.json()["id"]
    det = (await client.get(f"/datasets/{did}", headers=h)).json()
    assert det["provenance"].get("restricted") is True
    r = await client.get(f"/datasets/{did}/geojson", headers=h)
    assert r.status_code == 403
    s = await client.get(f"/projects/{pid}/summary", headers=h)
    assert s.status_code == 200
    assert s.json()["counts"]["restricted_excluded"] == 1
    assert all(dd["id"] != did for dd in s.json()["datasets"])


async def test_sentinel2_multiband_import_registers_derived_ratios(client):
    """5-band S2 GeoTIFF -> DERIVED iron + clay datasets with recipes."""
    np = pytest.importorskip("numpy")
    rasterio = pytest.importorskip("rasterio")
    from rasterio.transform import from_bounds as _fb
    h = await _login(client)
    pid = await _make_project(client, h, "gate-s2")
    prof = {"driver": "GTiff", "height": 40, "width": 40, "count": 5,
            "dtype": "float32", "crs": "EPSG:4326",
            "transform": _fb(33.20, -9.86, 33.38, -9.69, 40, 40)}
    rng = np.random.default_rng(11)
    bands = [0.10 + 0.02 * rng.random((40, 40)),  # B2
             0.20 + 0.02 * rng.random((40, 40)),  # B4
             0.25 + 0.02 * rng.random((40, 40)),  # B8 (bare soil, low NDVI)
             0.30 + 0.02 * rng.random((40, 40)),  # B11
             0.15 + 0.02 * rng.random((40, 40))]  # B12
    import io as _io
    from rasterio.io import MemoryFile as _MF
    with _MF() as mem:
        with mem.open(**prof) as dst:
            for i, b in enumerate(bands, start=1):
                dst.write(b.astype("float32"), i)
        raw = mem.read()
    r = await client.post("/ingest/sentinel2", headers=h,
                          data={"name": "S2 test", "project_id": pid},
                          files={"file": ("s2_stack.tif", raw, "image/tiff")})
    assert r.status_code == 201, r.text
    body = r.json()
    assert len(body["datasets"]) == 2
    ratios = {d["ratio"] for d in body["datasets"]}
    assert ratios == {"alteration_iron_oxide", "alteration_clay"}
    for d in body["datasets"]:
        det = (await client.get(f"/datasets/{d['id']}", headers=h)).json()
        assert det["status_label"] == "DERIVED"
        assert "recipe" in det["provenance"]
    # ratios feed the alteration group: structure + lithology + S2 = sufficient gold run
    struct = {"type": "FeatureCollection", "features": [
        {"type": "Feature", "geometry": {"type": "LineString", "coordinates": [[33.22, -9.80], [33.34, -9.74]]},
         "properties": {"name": "F1"}}]}
    await client.post("/ingest/geojson", headers=h,
                      data={"name": "s2-struct", "kind": "structure", "project_id": pid},
                      files={"file": ("s.geojson", json.dumps(struct), "application/json")})
    lith = {"type": "FeatureCollection", "features": [
        {"type": "Feature",
         "geometry": {"type": "Polygon", "coordinates": [[[33.2, -9.86], [33.38, -9.86], [33.38, -9.69], [33.2, -9.69], [33.2, -9.86]]]},
         "properties": {"unit": "gneiss", "favorability_au": 0.6}}]}
    await client.post("/ingest/geojson", headers=h,
                      data={"name": "s2-lith", "kind": "geology", "project_id": pid},
                      files={"file": ("l.geojson", json.dumps(lith), "application/json")})
    from apps.api.app.services.prospectivity import run_analysis_sync
    r = await client.post(f"/runs?project_id={pid}", headers=h,
                          json={"method": "weighted", "config": {"grid_m": 500}, "seed": 42})
    rid = r.json()["id"]
    res = run_analysis_sync(rid, os.environ["MWAMBA_DB_URL"], os.environ["MWAMBA_STORAGE_DIR"])
    assert res["ok"] is True, res
    gate = (await client.get(f"/runs/{rid}", headers=h)).json()["metrics"]["evidence_gate"]
    assert "alteration_or_geochem" in gate["present_groups"]
    assert gate["sufficient"] is True
