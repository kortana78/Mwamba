"""Determinism + correctness tests for the shared engine. No fake numbers — all
assertions computed from the functions themselves."""
import numpy as np
import pytest

from mwamba_geo.scoring import weighted_overlay, fuzzy_overlay, coverage_layer
from mwamba_geo.features import distance_decay, idw_interpolation, normalise_01, robust_anomaly_threshold
from mwamba_geo.validation import success_rate_curve, prediction_rate_curve, heldout_test, auc_score
from mwamba_geo.validate import validate_geojson, validate_csv, parse_detection_limit
from mwamba_geo.crs import reproject_point, in_malawi, MALAWI_BBOX


def test_weighted_overlay_ignores_nan():
    a = np.array([[1.0, np.nan], [0.0, 0.5]])
    b = np.array([[0.0, 0.5], [np.nan, 0.5]])
    r = weighted_overlay({"a": a, "b": b}, {"a": 0.5, "b": 0.5})
    assert r["score"][0, 0] == 0.5
    assert r["score"][0, 1] == 0.5  # only b present
    assert r["score"][1, 0] == 0.0  # only a present
    assert r["coverage"][0, 0] == 1.0
    assert r["coverage"][0, 1] == 0.5


def test_weighted_overlay_deterministic():
    rng = np.random.default_rng(7)
    layers = {"x": rng.random((20, 20)), "y": rng.random((20, 20))}
    r1 = weighted_overlay(layers, {"x": 0.7, "y": 0.3})["score"]
    r2 = weighted_overlay(layers, {"x": 0.7, "y": 0.3})["score"]
    assert np.array_equal(r1, r2, equal_nan=True)


def test_fuzzy_gamma_bounds():
    rng = np.random.default_rng(1)
    layers = {"a": rng.random((10, 10)), "b": rng.random((10, 10))}
    for op in ("and", "or", "gamma"):
        s = fuzzy_overlay(layers, gamma=0.85, operator=op)["score"]
        assert np.nanmin(s) >= 0.0 and np.nanmax(s) <= 1.0


def test_coverage_layer():
    a = np.array([[1.0, np.nan]])
    b = np.array([[1.0, 1.0]])
    c = coverage_layer({"a": a, "b": b})
    assert c.tolist() == [[1.0, 0.5]]


def test_distance_decay():
    d = np.array([[0.0, 1500.0]])
    f = distance_decay(d, 1500.0)
    assert abs(f[0, 0] - 1.0) < 1e-9
    assert abs(f[0, 1] - np.exp(-1)) < 1e-9


def test_idw_sparse_mask():
    gx, gy = np.meshgrid(np.arange(5.0), np.arange(5.0))
    v = idw_interpolation(gx, gy, np.array([0.0]), np.array([0.0]),
                          np.array([10.0]), nodata_radius_m=1.5)
    assert np.isfinite(v[0, 0])
    assert np.isnan(v[4, 4])  # far from sample -> missing, not zero


def test_anomaly_threshold():
    v = np.array([1, 2, 3, 4, 5, 100.0])
    t = robust_anomaly_threshold(v)
    assert t["median"] == 3.5
    assert t["threshold"] > t["median"]


def test_success_and_prediction_curves():
    score = np.array([[0.9, 0.1], [0.8, 0.2]])
    occ = np.array([[True, False], [True, False]])
    s = success_rate_curve(score, occ)
    assert s["ok"] and s["auc"] is not None and 0 <= s["auc"] <= 1
    p = prediction_rate_curve(score, occ)
    assert p["ok"] and p["curve"] == "prediction_rate"


def test_heldout_beats_random_on_good_model():
    score = np.array([[0.95, 0.05], [0.9, 0.1]])
    gx, gy = np.meshgrid(np.array([0.0, 1.0]), np.array([0.0, 1.0]))
    r = heldout_test(score, gx, gy, np.array([0.0]), np.array([0.0]), top_pct=50)
    assert r["ok"] and r["hit_rate"] == 1.0


def test_auc_perfect():
    score = np.array([0.9, 0.8, 0.1, 0.2])
    occ = np.array([True, True, False, False])
    assert auc_score(score, occ) == 1.0


def test_validate_geojson_and_dl_strings():
    assert parse_detection_limit("<0.01")["censored"] is True
    assert parse_detection_limit("5")["value"] == 5.0
    fc = {"type": "FeatureCollection", "features": [
        {"type": "Feature", "geometry": {"type": "Point", "coordinates": [33.27, -9.70]},
         "properties": {"Au_ppb": 10}},
        {"type": "Feature", "geometry": {"type": "Point", "coordinates": [33.27, -9.70]},
         "properties": {"Au_ppb": "<0.01"}},
        {"type": "Feature", "geometry": {"type": "Point", "coordinates": [0.0, 0.0]},
         "properties": {}},
    ]}
    rep = validate_geojson(fc, value_field="Au_ppb")
    assert rep["stats"]["n_total"] == 3
    assert any("outside Malawi" in w for w in rep["warnings"])
    assert any("duplicate" in w for w in rep["warnings"])


def test_validate_csv():
    text = "lon,lat,Au_ppb\n33.27,-9.70,10\n33.30,-9.72,<0.01\n0,0,5\n"
    rep = validate_csv(text)
    assert rep["stats"]["n_total"] == 3
    assert rep["stats"]["n_censored_dl"] == 1


def test_crs_roundtrip_and_malawi():
    x, y = reproject_point(33.27, -9.70, "EPSG:4326", "EPSG:32736")
    lon, lat = reproject_point(x, y, "EPSG:32736", "EPSG:4326")
    assert abs(lon - 33.27) < 1e-6 and abs(lat + 9.70) < 1e-6
    assert in_malawi(33.27, -9.70)
    assert not in_malawi(0.0, 0.0)
    assert MALAWI_BBOX == (32.6, -17.2, 35.9, -9.3)


def test_evidence_gate_blocks_single_proxy_layer():
    from mwamba_geo.evidence import evaluate_evidence, INSUFFICIENT_LABEL
    # a lone DEM slope surface must never count as a targeting result
    g = evaluate_evidence("Au", ["dem_slope"])
    assert g["sufficient"] is False
    assert set(g["missing_groups"]) == {"structure", "host_lithology", "alteration_or_geochem"}
    assert INSUFFICIENT_LABEL in (g["note"] or "")
    # full gold evidence is sufficient
    g2 = evaluate_evidence("Au", ["dist_structure", "lithology", "geochem_au"])
    assert g2["sufficient"] is True and g2["missing_groups"] == []
    # DEM lineaments satisfy the structure group
    g3 = evaluate_evidence("Au", ["lineament_density", "lithology", "alteration_clay"])
    assert g3["sufficient"] is True
    # REE needs radiometric/alkaline + structure; magnetics alone never suffices
    g4 = evaluate_evidence("REE", ["magnetics", "dist_structure"])
    assert g4["sufficient"] is False
    assert "radiometric_or_alkaline_lithology" in g4["missing_groups"]
    g5 = evaluate_evidence("REE", ["alkaline_lithology", "lineament_density"])
    assert g5["sufficient"] is True


def _ridge_dem(n: int = 48) -> np.ndarray:
    yy, xx = np.mgrid[0:n, 0:n].astype(float)
    dem = 1500.0 - 0.8 * np.abs(xx - n / 2) + 30.0 * np.sin(xx / 4.0) + 8.0 * np.sin(yy / 3.0)
    return dem


def test_lineament_extraction_deterministic():
    from mwamba_geo.features import extract_lineaments
    dem = _ridge_dem()
    gx, gy = np.meshgrid(np.arange(48.0) * 100.0, np.arange(48.0) * 100.0)
    kw = dict(grid_m=100.0, edge_percentile=90.0, min_length_m=500.0)
    r1 = extract_lineaments(dem, gx, gy, **kw)
    r2 = extract_lineaments(dem, gx, gy, **kw)
    assert r1["segments"] == r2["segments"]
    assert np.array_equal(r1["binary"], r2["binary"], equal_nan=True)
    assert r1["n_lineaments"] >= 1  # the synthetic ridge must yield structure
    for (x1, y1, x2, y2) in r1["segments"]:
        assert np.hypot(x2 - x1, y2 - y1) >= 500.0 - 1e-6


def test_lineament_extraction_on_real_fixture_dem():
    rasterio = pytest.importorskip("rasterio")
    import os
    from mwamba_geo.features import extract_lineaments
    dem_path = os.path.normpath(os.path.join(os.path.dirname(__file__), "..", "..", "..",
                                             "data", "real", "chitipa_dem_30m.tif"))
    if not os.path.exists(dem_path):
        pytest.skip("real fixture DEM absent")
    with rasterio.open(dem_path) as src:
        arr = src.read(1).astype(float)
        if src.nodata is not None:
            arr[arr == src.nodata] = np.nan
        resx = abs(src.transform.a)
        resy = abs(src.transform.e)
        if src.crs.is_geographic:
            resx *= 111320.0
            resy *= 111320.0
        gm = (resx + resy) / 2.0
    # downsample for test speed; determinism is what matters
    step = max(1, int(max(arr.shape) / 120))
    sub = arr[::step, ::step]
    gx, gy = np.meshgrid(np.arange(sub.shape[1]) * gm * step,
                         np.arange(sub.shape[0]) * gm * step)
    a = extract_lineaments(sub, gx, gy, grid_m=gm * step)
    b = extract_lineaments(sub, gx, gy, grid_m=gm * step)
    assert a["segments"] == b["segments"]
    assert a["n_lineaments"] >= 1


def test_drainage_deterministic_and_masked():
    from mwamba_geo.features import dem_drainage, drainage_density_layer
    dem = _ridge_dem()
    gx, gy = np.meshgrid(np.arange(48.0) * 100.0, np.arange(48.0) * 100.0)
    d1 = dem_drainage(dem, gx, gy, 100.0)
    d2 = dem_drainage(dem, gx, gy, 100.0)
    assert np.array_equal(d1["accumulation"], d2["accumulation"], equal_nan=True)
    assert d1["segments"] == d2["segments"]
    assert len(d1["segments"]) >= 1
    dens = drainage_density_layer(d1["accumulation"], d1["mask"])
    assert np.nanmin(dens) >= 0.0 and np.nanmax(dens) <= 1.0
    assert np.isnan(dens[~d1["mask"]]).all()  # outside network = missing, not zero


def test_sentinel2_ratios_mask_vegetation():
    from mwamba_geo.features import sentinel2_ratios
    n = 10
    b2 = np.full((n, n), 0.10)
    b4 = np.full((n, n), 0.20)   # iron = 2.0
    b8 = np.full((n, n), 0.60)   # vegetated half below
    b11 = np.full((n, n), 0.30)
    b12 = np.full((n, n), 0.15)  # clay = 2.0
    b8[:, 5:] = 0.21             # bare half: ndvi ~ 0.02
    r1 = sentinel2_ratios(b2, b4, b8, b11, b12)
    r2 = sentinel2_ratios(b2, b4, b8, b11, b12)
    assert np.array_equal(r1["iron_oxide"], r2["iron_oxide"], equal_nan=True)
    assert abs(float(np.nanmean(r1["iron_oxide"])) - 2.0) < 1e-9
    assert abs(float(np.nanmean(r1["clay"])) - 2.0) < 1e-9
    assert r1["vegetation_mask"][:, :5].all() and not r1["vegetation_mask"][:, 5:].any()
    assert np.isnan(r1["alteration_mask"][:, :5]).all()  # veg masked, not zeroed
    assert (r1["alteration_mask"][:, 5:] == 1.0).all()
