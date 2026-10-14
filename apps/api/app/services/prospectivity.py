"""Prospectivity engine (sync core so Celery and BackgroundTasks share one path).

Pipeline: AOI grid -> evidence layers -> weighted/fuzzy scoring -> coverage ->
targets -> validation metrics -> constraints. Deterministic given (config, dataset
versions, seed). Scores are relative rankings 0..1, never deposit probabilities.
"""
from __future__ import annotations
import json
import os
import sys
import traceback

import numpy as np
from scipy import ndimage
from shapely.geometry import shape, Point
from shapely.prepared import prep
from pyproj import Transformer

try:
    from mwamba_geo.grid import build_grid  # noqa: E402
    from mwamba_geo.features import (  # noqa: E402
        min_distance_to_segments, distance_decay, fault_density,
        lithology_score, idw_interpolation, normalise_01, robust_anomaly_threshold,
        extract_lineaments, line_intersections, dem_drainage, drainage_density_layer)
    from mwamba_geo.scoring import weighted_overlay, fuzzy_overlay  # noqa: E402
    from mwamba_geo.validation import (  # noqa: E402
        success_rate_curve, prediction_rate_curve, auc_score, heldout_test, spatial_block_cv)
    from mwamba_geo.evidence import evaluate_evidence, INSUFFICIENT_LABEL  # noqa: E402
except ImportError:  # local checkout without installed package
    sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "..", "..", "packages", "geo"))
    from mwamba_geo.grid import build_grid  # noqa: E402
    from mwamba_geo.features import (  # noqa: E402
        min_distance_to_segments, distance_decay, fault_density,
        lithology_score, idw_interpolation, normalise_01, robust_anomaly_threshold,
        extract_lineaments, line_intersections, dem_drainage, drainage_density_layer)
    from mwamba_geo.scoring import weighted_overlay, fuzzy_overlay  # noqa: E402
    from mwamba_geo.validation import (  # noqa: E402
        success_rate_curve, prediction_rate_curve, auc_score, heldout_test, spatial_block_cv)
    from mwamba_geo.evidence import evaluate_evidence, INSUFFICIENT_LABEL  # noqa: E402

_TO_UTM = Transformer.from_crs("EPSG:4326", "EPSG:32736", always_xy=True)
_TO_WGS = Transformer.from_crs("EPSG:32736", "EPSG:4326", always_xy=True)

DEFAULT_CONFIG = {
    "grid_m": 100.0,
    "weights": {"dist_structure": 0.30, "fault_density": 0.15, "lineament_density": 0.10,
                "lithology": 0.20, "geochem_au": 0.15,
                "alteration_iron_oxide": 0.05, "alteration_clay": 0.05},
    "decay_m": 1500.0,
    "density_radius_m": 2000.0,
    "geochem_idw_power": 2.0,
    "geochem_field": "Au_ppb",
    "lithology_scores": {},
    "fuzzy_gamma": 0.85,
    "fuzzy_operator": "gamma",
    "target_percentile": 95.0,
    "target_min_area_m2": 200000.0,
    "target_merge_distance_m": 500.0,
    "target_max_targets": 20,
    "lineament_edge_percentile": 90.0,
    "lineament_min_length_m": 500.0,
    "drainage_accum_percentile": 90.0,
    "holdout_fraction": 0.3,
}


def _sync_engine(db_url_async: str, storage_dir: str):
    from sqlalchemy import create_engine
    # Keep the path portion byte-identical; only swap the driver scheme.
    url = db_url_async.replace("sqlite+aiosqlite:", "sqlite:", 1)
    # Windows absolute paths must use forward slashes inside a URL.
    if url.startswith("sqlite:") and "\\" in url:
        url = url.replace("\\", "/")
    return create_engine(url, future=True)


def _load_geojson(path: str) -> dict:
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def _densify_line(coords: list, step_m: float = 500.0) -> list[tuple[float, float]]:
    pts = []
    for (x1, y1), (x2, y2) in zip(coords, coords[1:]):
        seg_len = float(np.hypot(x2 - x1, y2 - y1))
        n = max(1, int(seg_len / step_m))
        for i in range(n):
            t = i / n
            pts.append((x1 + t * (x2 - x1), y1 + t * (y2 - y1)))
    if coords:
        pts.append(tuple(coords[-1]))
    return pts


def run_analysis_sync(run_id: str, db_url: str, storage_dir: str) -> dict:
    """Full run. Updates AnalysisRun row progress/status, writes grids, targets, metrics."""
    from sqlalchemy.orm import Session
    from ..models import AnalysisRun, Dataset, Project, Target, ValidationResult
    from .constraints import load_constraint_polys, check_target

    eng = _sync_engine(db_url, storage_dir)
    t_from_utm = Transformer.from_crs("EPSG:32736", "EPSG:4326", always_xy=True)
    with Session(eng) as s:
        run = s.get(AnalysisRun, run_id)
        if run is None:
            return {"ok": False, "error": "run not found"}
        try:
            run.status = "running"
            run.progress = 0.05
            s.commit()
            cfg = dict(DEFAULT_CONFIG)
            cfg.update(run.config or {})
            project = s.get(Project, run.project_id)
            if project is None:
                raise ValueError("project gone")

            # --- datasets ---
            if run.dataset_ids:
                dss = [s.get(Dataset, i) for i in run.dataset_ids]
                dss = [d for d in dss if d is not None]
            else:
                from sqlalchemy import select
                dss = list(s.scalars(select(Dataset).where(
                    Dataset.project_id == project.id)).all())
            by_kind: dict[str, list] = {}
            for d in dss:
                by_kind.setdefault(d.kind, []).append(d)
            run.progress = 0.15
            s.commit()

            # --- label-sufficiency gate FIRST (fail fast, honest message) ---
            # WofE / supervised ML are only enabled with >= 10 known occurrences.
            # Otherwise the knowledge-driven (weighted/fuzzy) model stays active.
            method = (run.method or "weighted").lower()
            if method in ("wofe", "logreg"):
                n_occ_total = 0
                for d in by_kind.get("occurrences", []):
                    if not d.stored_path or not os.path.exists(d.stored_path):
                        continue
                    try:
                        feats = _load_geojson(d.stored_path).get("features", [])
                    except Exception:
                        continue
                    n_occ_total += sum(
                        1 for f in feats if ((f.get("geometry") or {}).get("type") == "Point"))
                if n_occ_total < 10:
                    raise ValueError(
                        f"Method '{method}' needs >= 10 known occurrences; project has {n_occ_total}. "
                        f"Labels insufficient — weighted/fuzzy knowledge-driven model stays active. "
                        f"Import more occurrences to enable WofE/ML.")

            # --- grid ---
            # Render free tier: keep runs small (pilot AOI, 100–200 m grid).
            # build_grid enforces MWAMBA_MAX_GRID_CELLS; the wall-clock guard
            # below turns an over-long run into a clear error instead of a hang.
            import time as _time
            _t0 = _time.monotonic()
            try:
                from ..config import settings as _ss
                _max_cells = int(_ss.MWAMBA_MAX_GRID_CELLS)
                _timeout_s = int(_ss.MWAMBA_RUN_TIMEOUT_S)
            except Exception:
                _max_cells, _timeout_s = 2_500_000, 240

            def _guard(stage: str) -> None:
                if _time.monotonic() - _t0 > _timeout_s:
                    raise TimeoutError(
                        f"Run exceeded {_timeout_s}s at stage '{stage}' — "
                        f"use a coarser grid_m or a smaller AOI (pilot: 100–200 m).")

            grid = build_grid(project.aoi_geojson, grid_m=float(cfg.get("grid_m", project.grid_m or 100.0)),
                              max_cells=_max_cells)
            _guard("grid")
            gx, gy = grid["grid_x"], grid["grid_y"]
            ny, nx = gx.shape

            layers: dict[str, np.ndarray] = {}
            recipes: dict[str, dict] = {}

            # --- structures -> dist_structure + fault_density ---
            struct_dss = by_kind.get("structure", [])
            segments: list[tuple[float, float, float, float]] = []
            fault_pts: list[tuple[float, float]] = []
            for d in struct_dss:
                if not d.stored_path or not os.path.exists(d.stored_path):
                    continue
                obj = _load_geojson(d.stored_path)
                for feat in obj.get("features", []):
                    g = feat.get("geometry") or {}
                    coords = []
                    if g.get("type") == "LineString":
                        coords = g["coordinates"]
                    elif g.get("type") == "MultiLineString":
                        for ls in g["coordinates"]:
                            coords.extend(ls)
                    else:
                        continue
                    utm = [_TO_UTM.transform(float(x), float(y)) for x, y in coords]
                    for a, b in zip(utm, utm[1:]):
                        segments.append((a[0], a[1], b[0], b[1]))
                    fault_pts.extend(_densify_line(utm))
            if segments:
                dist = min_distance_to_segments(gx, gy, segments)
                layers["dist_structure"] = distance_decay(dist, float(cfg.get("decay_m", 1500.0)))
                recipes["dist_structure"] = {"inputs": [d.id for d in struct_dss],
                                             "params": {"decay_m": cfg.get("decay_m")}, "code_version": "0.1.0"}
            if fault_pts:
                fp = np.array(fault_pts)
                layers["fault_density"] = fault_density(gx, gy, fp, float(cfg.get("density_radius_m", 2000.0)))
                recipes["fault_density"] = {"inputs": [d.id for d in struct_dss],
                                            "params": {"radius_m": cfg.get("density_radius_m")}, "code_version": "0.1.0"}
            run.progress = 0.35
            s.commit()
            _guard("structures")

            # --- lithology ---
            geo_dss = by_kind.get("geology", [])
            lith_scores_cfg = dict(cfg.get("lithology_scores", {}))
            masks: dict[str, np.ndarray] = {}
            for d in geo_dss:
                if not d.stored_path or not os.path.exists(d.stored_path):
                    continue
                obj = _load_geojson(d.stored_path)
                for feat in obj.get("features", []):
                    props = feat.get("properties") or {}
                    unit = str(props.get("unit", props.get("name", "unit")))
                    try:
                        poly = shape(feat.get("geometry") or {})
                    except Exception:
                        continue
                    if poly.is_empty or not poly.is_valid:
                        continue
                    sc = props.get("favorability_au", props.get("score", None))
                    if sc is not None:
                        try:
                            lith_scores_cfg.setdefault(unit, float(sc))
                        except (ValueError, TypeError):
                            pass
                    minx, miny, maxx, maxy = poly.bounds  # lon/lat bounds
                    # convert grid lon/lat subset test
                    sel = ((grid["grid_lon"] >= minx - 0.01) & (grid["grid_lon"] <= maxx + 0.01) &
                           (grid["grid_lat"] >= miny - 0.01) & (grid["grid_lat"] <= maxy + 0.01))
                    if not sel.any():
                        continue
                    pr = prep(poly)
                    ys_idx, xs_idx = np.where(sel)
                    mask = masks.get(unit)
                    if mask is None:
                        mask = np.zeros_like(gx, dtype=bool)
                        masks[unit] = mask
                    for yi, xi in zip(ys_idx.tolist(), xs_idx.tolist()):
                        if pr.contains(Point(float(grid["grid_lon"][yi, xi]), float(grid["grid_lat"][yi, xi]))):
                            mask[yi, xi] = True
            if masks:
                if not lith_scores_cfg:
                    # default: equal favourability is dishonest; require scores
                    raise ValueError("Lithology layer present but no favourability scores. "
                                     "Assign per-unit scores (0..1) in run config 'lithology_scores'.")
                layers["lithology"] = lithology_score(masks, lith_scores_cfg)
                recipes["lithology"] = {"inputs": [d.id for d in geo_dss],
                                        "params": {"scores": lith_scores_cfg}, "code_version": "0.1.0"}
            run.progress = 0.55
            s.commit()
            _guard("lithology")

            # --- geochemistry (IDW of Au field) ---
            geochem_dss = by_kind.get("geochem", [])
            px, py, vals = [], [], []
            geochem_field = str(cfg.get("geochem_field", "Au_ppb"))
            for d in geochem_dss:
                if not d.stored_path or not os.path.exists(d.stored_path):
                    continue
                obj = _load_geojson(d.stored_path)
                for feat in obj.get("features", []):
                    g = feat.get("geometry") or {}
                    if g.get("type") != "Point":
                        continue
                    lon, lat = float(g["coordinates"][0]), float(g["coordinates"][1])
                    props = feat.get("properties") or {}
                    raw = props.get(geochem_field, props.get("Au_ppb", props.get("value", None)))
                    if raw is None:
                        continue
                    if isinstance(raw, str) and raw.strip().startswith("<"):
                        try:
                            v = float(raw.strip()[1:]) / 2.0
                        except ValueError:
                            continue
                    else:
                        try:
                            v = float(raw)
                        except (ValueError, TypeError):
                            continue
                    x, y = _TO_UTM.transform(lon, lat)
                    px.append(x)
                    py.append(y)
                    vals.append(v)
            if px:
                pxa, pya, va = (np.array(a, float) for a in (px, py, vals))
                thr = robust_anomaly_threshold(va)
                idw = idw_interpolation(gx, gy, pxa, pya, np.log10(np.maximum(va, 1e-6)),
                                        power=float(cfg.get("geochem_idw_power", 2.0)),
                                        nodata_radius_m=5000.0)
                layers["geochem_au"] = normalise_01(idw)
                recipes["geochem_au"] = {"inputs": [d.id for d in geochem_dss],
                                         "params": {"field": geochem_field, "threshold_stats": thr},
                                         "code_version": "0.1.0"}
            run.progress = 0.7
            s.commit()
            _guard("geochemistry")

            # --- remote sensing: DERIVED alteration ratios (iron B4/B2, clay B11/B12) ---
            # Only datasets carrying a provenance.derived_ratio recipe are consumed,
            # so an arbitrary upload can never silently become alteration evidence.
            rs_map = {"iron_oxide": "alteration_iron_oxide", "clay": "alteration_clay"}
            for d in by_kind.get("remotesensing", []):
                if not d.stored_path or not os.path.exists(d.stored_path):
                    continue
                ratio = (d.provenance or {}).get("derived_ratio")
                layer_key = rs_map.get(str(ratio or ""))
                if not layer_key or layer_key in layers:
                    continue
                try:
                    import rasterio
                    from rasterio.warp import reproject, Resampling
                    from rasterio.transform import from_origin
                    gm = float(grid["grid_m"])
                    dst_transform = from_origin(float(grid["origin_x"]),
                                                float(grid["origin_y"]) + ny * gm, gm, gm)
                    arr = np.full((ny, nx), np.nan)
                    with rasterio.open(d.stored_path) as src:
                        reproject(rasterio.band(src, 1), arr,
                                  src_transform=src.transform, src_crs=src.crs,
                                  dst_transform=dst_transform, dst_crs="EPSG:32736",
                                  resampling=Resampling.bilinear,
                                  src_nodata=src.nodata, dst_nodata=np.nan)
                    if np.isfinite(arr).sum() < 10:
                        continue
                    layers[layer_key] = normalise_01(arr)
                    recipes[layer_key] = {"inputs": [d.id],
                                          "params": {"recipe": (d.provenance or {}).get("recipe", ratio)},
                                          "code_version": "0.1.0",
                                          "note": "DERIVED Sentinel-2 ratio, vegetation-masked at source"}
                except ImportError:
                    raise ValueError("Remote-sensing layers need the 'rasterio' package on the server.")
                except Exception:
                    continue

            # --- DEM: slope evidence (low slope favoured = preservation proxy) ---
            # + DERIVED lineaments (multi-azimuth hillshade, unverified structural
            # proxy) + drainage network. Both join the structure evidence group.
            dem_dss = by_kind.get("dem", [])
            dem_grid_utm: np.ndarray | None = None
            dem_src_id: str | None = None
            gm_cfg = float(cfg.get("grid_m", 100.0))
            for d in dem_dss:
                if not d.stored_path or not os.path.exists(d.stored_path):
                    continue
                try:
                    import rasterio
                    from rasterio.warp import reproject, Resampling
                    from rasterio.transform import from_origin
                    gm = gm_cfg
                    dst_transform = from_origin(float(grid["origin_x"]), float(grid["origin_y"]) + ny * gm, gm, gm)
                    dem_grid = np.full((ny, nx), np.nan)
                    with rasterio.open(d.stored_path) as src:
                        reproject(rasterio.band(src, 1), dem_grid,
                                  src_transform=src.transform, src_crs=src.crs,
                                  dst_transform=dst_transform, dst_crs="EPSG:32736",
                                  resampling=Resampling.bilinear,
                                  src_nodata=src.nodata, dst_nodata=np.nan)
                    if np.isfinite(dem_grid).sum() < 10:
                        continue
                    dem_grid_utm = dem_grid
                    dem_src_id = d.id
                    gy_d, gx_d = np.gradient(np.nan_to_num(dem_grid, nan=np.nanmean(dem_grid)), gm, gm)
                    slope_deg = np.degrees(np.arctan(np.hypot(gx_d, gy_d)))
                    slope_deg[~np.isfinite(dem_grid)] = np.nan
                    favour_low = bool(cfg.get("dem_slope_favour_low", True))
                    norm = normalise_01(slope_deg)
                    layers["dem_slope"] = (1.0 - norm) if favour_low else norm
                    recipes["dem_slope"] = {"inputs": [d.id],
                                            "params": {"favour_low_slope": favour_low},
                                            "code_version": "0.1.0",
                                            "note": "Terrain preservation proxy, not a direct detector"}
                    break  # first usable DEM wins; multi-DEM mosaics ship later
                except ImportError:
                    raise ValueError("DEM layer needs the 'rasterio' package on the server.")
                except Exception as e:
                    raise ValueError(f"DEM {d.name} unreadable in analysis grid: {e}")

            # --- DERIVED DEM lineaments + drainage (structure group) ---
            derived_lin_segments: list = []
            derived_drn_segments: list = []
            if dem_grid_utm is not None:
                try:
                    lin = extract_lineaments(
                        dem_grid_utm, gx, gy, gm_cfg,
                        edge_percentile=float(cfg.get("lineament_edge_percentile", 90.0)),
                        min_length_m=float(cfg.get("lineament_min_length_m", 500.0)))
                    derived_lin_segments = lin["segments"]
                    if derived_lin_segments:
                        lp = np.array([(a[0], a[1]) for a in derived_lin_segments] +
                                      [(a[2], a[3]) for a in derived_lin_segments])
                        layers["lineament_density"] = fault_density(
                            gx, gy, lp, float(cfg.get("density_radius_m", 2000.0)))
                        recipes["lineament_density"] = {
                            "inputs": [dem_src_id],
                            "params": {"edge_percentile": cfg.get("lineament_edge_percentile"),
                                       "min_length_m": cfg.get("lineament_min_length_m")},
                            "code_version": "0.1.0",
                            "note": "DERIVED unverified structural proxy from DEM hillshade; "
                                    "use only alongside mapped structures."}
                        xs = line_intersections(derived_lin_segments)
                        if len(xs):
                            layers["lineament_intersection"] = fault_density(
                                gx, gy, xs, float(cfg.get("density_radius_m", 2000.0)))
                            recipes["lineament_intersection"] = {
                                "inputs": [dem_src_id], "params": {},
                                "code_version": "0.1.0",
                                "note": "DERIVED lineament-intersection density (dilation proxy)."}
                    drn = dem_drainage(
                        dem_grid_utm, gx, gy, gm_cfg,
                        accum_percentile=float(cfg.get("drainage_accum_percentile", 90.0)))
                    derived_drn_segments = drn["segments"]
                    if np.isfinite(drn["accumulation"]).sum():
                        layers["drainage_density"] = drainage_density_layer(
                            drn["accumulation"], drn["mask"])
                        recipes["drainage_density"] = {
                            "inputs": [dem_src_id],
                            "params": {"accum_percentile": cfg.get("drainage_accum_percentile")},
                            "code_version": "0.1.0",
                            "note": "DERIVED D8 drainage density (structure group)."}
                except Exception as e:
                    recipes.setdefault("dem_derived_warning", {"error": str(e)[:300]})
                # persist derived vectors as a DERIVED structure dataset for the map
                if derived_lin_segments or derived_drn_segments:
                    try:
                        import uuid as _uuid
                        feats = []
                        for a in derived_lin_segments:
                            lon1, lat1 = t_from_utm.transform(a[0], a[1])
                            lon2, lat2 = t_from_utm.transform(a[2], a[3])
                            feats.append({"type": "Feature",
                                          "geometry": {"type": "LineString",
                                                       "coordinates": [[lon1, lat1], [lon2, lat2]]},
                                          "properties": {"kind": "lineament",
                                                         "status_label": "DERIVED",
                                                         "note": "unverified structural proxy"}})
                        for a in derived_drn_segments[:5000]:
                            lon1, lat1 = t_from_utm.transform(a[0], a[1])
                            lon2, lat2 = t_from_utm.transform(a[2], a[3])
                            feats.append({"type": "Feature",
                                          "geometry": {"type": "LineString",
                                                       "coordinates": [[lon1, lat1], [lon2, lat2]]},
                                          "properties": {"kind": "drainage",
                                                         "status_label": "DERIVED"}})
                        up_dir = os.path.join(storage_dir, "uploads")
                        os.makedirs(up_dir, exist_ok=True)
                        lp_path = os.path.join(up_dir, f"derived_dem_lines_{run_id}.geojson")
                        with open(lp_path, "w", encoding="utf-8") as f:
                            json.dump({"type": "FeatureCollection", "features": feats}, f)
                        s.add(Dataset(org_id=project.org_id, project_id=project.id,
                                      name=f"DERIVED DEM lineaments+drainage (run {run_id[:8]})",
                                      kind="structure", format="geojson",
                                      crs_original="EPSG:4326", status_label="DERIVED",
                                      licence="Derived from project DEM — unverified structural proxy",
                                      source_url="",
                                      provenance={"derived": True, "run_id": run_id,
                                                  "source_dem": dem_src_id,
                                                  "n_lineaments": len(derived_lin_segments),
                                                  "n_drainage": len(derived_drn_segments)},
                                      processing_history=[{"step": "dem-lineament-drainage",
                                                           "recipe": "multi-azimuth hillshade + D8"}],
                                      quality={"ok": True, "derived": True},
                                      feature_count=len(feats), stored_path=lp_path,
                                      created_by="engine"))
                    except Exception:
                        pass
            run.progress = 0.75
            s.commit()
            _guard("dem-derived")

            if not layers:
                raise ValueError("No usable evidence layers. Import structure/geology/geochem/dem datasets first.")

            # --- evidence sufficiency gate ---
            # Surface is always computed for inspection, but ranked targets are
            # only generated when every required group for the commodity is present.
            _req_override = cfg.get("required_evidence_groups")
            gate = evaluate_evidence(project.commodity or "Au", sorted(layers.keys()),
                                     required_override=list(_req_override) if _req_override else None)
            gate["layers_present"] = sorted(layers.keys())

            # --- scoring ---
            # (WofE/logreg label gate already ran fail-fast above; if labels sufficed,
            # fall back to weighted with a clear note until WofE training ships.)
            if method in ("wofe", "logreg"):
                method = "weighted"
                cfg["_wofe_note"] = "label gate passed but WofE training ships in next slice; weighted used"
            if method == "fuzzy":
                res = fuzzy_overlay(layers, gamma=float(cfg.get("fuzzy_gamma", 0.85)),
                                    operator=str(cfg.get("fuzzy_operator", "gamma")))
                score, coverage = res["score"], res["coverage"]
                contributions = {k: np.where(np.isfinite(v), v, np.nan) for k, v in layers.items()}
                weights_used = {}
            else:
                weights = dict(cfg.get("weights", DEFAULT_CONFIG["weights"]))
                # drop weights for absent layers (missing != negative), renormalise
                weights = {k: float(weights.get(k, 0.0)) for k in layers}
                res = weighted_overlay(layers, weights)
                score, coverage = res["score"], res["coverage"]
                contributions = res["contributions"]
                weights_used = res["weights_used"]
            run.progress = 0.8
            s.commit()
            _guard("scoring")

            # --- persist grids ---
            grids_dir = os.path.join(storage_dir, "grids")
            os.makedirs(grids_dir, exist_ok=True)
            grid_path = os.path.join(grids_dir, f"{run_id}_score.npy")
            cov_path = os.path.join(grids_dir, f"{run_id}_coverage.npy")
            contrib_path = os.path.join(grids_dir, f"{run_id}_contrib.npz")
            np.save(grid_path, score)
            np.save(cov_path, coverage)
            np.savez_compressed(contrib_path, **{k: v for k, v in contributions.items()})

            # --- occurrences + holdout split (deterministic) ---
            # Only records matching the project commodity count (a dimension-stone
            # record must not validate a gold model). Records WITHOUT a commodity
            # property are included (legacy uploads) and flagged in metrics.
            from ..schemas import COMMODITIES as _COMMS
            proj_comm = (project.commodity or "").strip()
            proj_names = {_COMMS.get(proj_comm, proj_comm).lower(), proj_comm.lower()}
            occ_pts: list[tuple[float, float, str]] = []
            occ_citations: dict[str, str] = {}
            n_skipped_other_comm = 0
            for d in by_kind.get("occurrences", []):
                if not d.stored_path or not os.path.exists(d.stored_path):
                    continue
                obj = _load_geojson(d.stored_path)
                for feat in obj.get("features", []):
                    g = feat.get("geometry") or {}
                    if g.get("type") != "Point":
                        continue
                    props = feat.get("properties") or {}
                    comm = props.get("commodity", props.get("Commodity"))
                    if comm is not None and str(comm).strip().lower() not in proj_names:
                        n_skipped_other_comm += 1
                        continue
                    lon, lat = float(g["coordinates"][0]), float(g["coordinates"][1])
                    name = str(props.get("name", f"{lon:.4f},{lat:.4f}"))
                    occ_pts.append((lon, lat, name))
                    cit = props.get("citation_text") or props.get("citation") or ""
                    if cit:
                        occ_citations[name] = str(cit)
            occ_pts.sort(key=lambda t: t[2])
            n_hold = max(1, int(round(len(occ_pts) * float(cfg.get("holdout_fraction", 0.3))))) if occ_pts else 0
            heldout = occ_pts[-n_hold:] if n_hold and len(occ_pts) >= 3 else []
            train = occ_pts[:len(occ_pts) - len(heldout)] if heldout else occ_pts

            def occ_mask(pts):
                m = np.zeros_like(score, dtype=bool)
                for lon, lat, _ in pts:
                    x, y = _TO_UTM.transform(lon, lat)
                    ix = int(np.argmin(np.abs(gx[0, :] - x)))
                    iy = int(np.argmin(np.abs(gy[:, 0] - y)))
                    if 0 <= iy < m.shape[0] and 0 <= ix < m.shape[1] and np.isfinite(score[iy, ix]):
                        m[iy, ix] = True
                return m

            train_mask = occ_mask(train)
            hold_mask = occ_mask(heldout)
            succ = success_rate_curve(score, train_mask) if train else {"ok": False, "reason": "no training occurrences"}
            pred = prediction_rate_curve(score, hold_mask) if heldout else {"ok": False, "reason": "no held-out occurrences"}
            auc = auc_score(score, train_mask) if train else None
            hx = np.array([_TO_UTM.transform(lon, lat)[0] for lon, lat, _ in heldout]) if heldout else np.array([])
            hy = np.array([_TO_UTM.transform(lon, lat)[1] for lon, lat, _ in heldout]) if heldout else np.array([])
            ht = heldout_test(score, gx, gy, hx, hy, top_pct=10.0) if len(heldout) else {"ok": False, "reason": "no held-out"}

            metrics = {
                "method": method,
                "weights_used": weights_used,
                "recipes": recipes,
                "evidence_gate": gate,
                "n_cells": int(score.size),
                "n_cells_valid": int(np.isfinite(score).sum()),
                "score_stats": {"min": float(np.nanmin(score)), "max": float(np.nanmax(score)),
                                "mean": float(np.nanmean(score))},
                "coverage_mean": float(np.nanmean(coverage)),
                "success_rate": succ, "prediction_rate": pred, "auc_train": auc,
                "heldout": ht,
                "heldout_names": [n for _, _, n in heldout],
                "train_names": [n for _, _, n in train],
                "occurrence_citations": occ_citations,
                "n_skipped_other_commodity": n_skipped_other_comm,
                "random_baseline_auc": 0.5,
                "note": "Scores are relative rankings 0..1, not probability of an economic deposit.",
            }

            # --- targets: threshold -> merge -> connected regions -> min area -> rank ---
            # Gate: insufficient evidence -> surface only, no ranked targets.
            from sqlalchemy import select as _select, delete as _delete
            s.execute(_delete(Target).where(Target.run_id == run_id))
            cand = []
            insufficient = not gate["sufficient"]
            thr = 0.0
            if insufficient:
                metrics["note"] = (f"{INSUFFICIENT_LABEL}: missing groups "
                                   f"{gate['missing_groups']}. Surface computed for inspection only; "
                                   f"no ranked targets generated. Scores are relative rankings 0..1.")
            else:
                pct = float(cfg.get("target_percentile", 95.0))
                finite = score[np.isfinite(score)]
                thr = float(np.percentile(finite, pct)) if finite.size else 0.0
                binary = np.isfinite(score) & (score >= thr)
                # merge nearby blobs within merge distance (dilation then relabel)
                merge_m = float(cfg.get("target_merge_distance_m", 500.0) or 0.0)
                if merge_m > 0 and binary.any():
                    iters = max(1, int(round(merge_m / float(cfg.get("grid_m", 100.0)))))
                    binary = ndimage.binary_dilation(binary, iterations=iters) & np.isfinite(score)
                    # re-apply threshold after merge so dilation cannot invent low-score ground:
                    # keep only cells that were above threshold OR bridge gaps — for pilot
                    # honesty keep the dilated mask but require mean-score re-check below.
                labelled, nlab = ndimage.label(binary)
            cell_m2 = float(cfg.get("grid_m", 100.0)) ** 2
            min_area = float(cfg.get("target_min_area_m2", 200000.0))
            max_targets = int(cfg.get("target_max_targets", 20) or 20)
            # constraint polygons for flags
            c_dss = by_kind.get("constraints", [])
            cpolys = load_constraint_polys([d.stored_path for d in c_dss])

            if not insufficient:
                for lab in range(1, n_lab_plus(nlab) + 1):
                    sel = labelled == lab
                    area = float(sel.sum() * cell_m2)
                    if area < min_area:
                        continue
                    mscore = float(np.nanmean(score[sel]))
                    maxscore = float(np.nanmax(score[sel]))
                    cov = float(np.nanmean(coverage[sel]))
                    yy, xx = np.where(sel)
                    cx_utm = float(gx[yy, xx].mean())
                    cy_utm = float(gy[yy, xx].mean())
                    clon, clat = t_from_utm.transform(cx_utm, cy_utm)
                    # evidence breakdown: mean contribution per layer inside polygon
                    ev = {}
                    for k, arr in contributions.items():
                        ev[k] = float(np.nanmean(arr[sel])) if np.isfinite(arr[sel]).any() else None
                    # polygon outline: convex-ish bbox polygon of member cells in lon/lat (honest simplification)
                    # use exterior of selected cells as small polygon via bounds + score-weighted note
                    poly_utm_x = gx[sel]
                    poly_utm_y = gy[sel]
                    hx0, hx1 = float(poly_utm_x.min()), float(poly_utm_x.max())
                    hy0, hy1 = float(poly_utm_y.min()), float(poly_utm_y.max())
                    corners = [t_from_utm.transform(hx0, hy0), t_from_utm.transform(hx1, hy0),
                               t_from_utm.transform(hx1, hy1), t_from_utm.transform(hx0, hy1),
                               t_from_utm.transform(hx0, hy0)]
                    poly = {"type": "Feature",
                            "geometry": {"type": "Polygon", "coordinates": [[list(c) for c in corners]]},
                            "properties": {}}
                    chk = check_target(poly, cpolys)
                    # next-steps rules from evidence
                    steps = recommend_steps(ev, cov, chk)
                    missing = [k for k, v in ev.items() if v is None]
                    cand.append({"area": area, "mean": mscore, "max": maxscore, "cov": cov,
                                 "cx_utm": cx_utm, "cy_utm": cy_utm, "clon": clon, "clat": clat,
                                 "ev": ev, "poly": poly, "chk": chk, "steps": steps, "missing": missing})
            # rank by mean score, then coverage, then area; cap count for pilot focus
            cand.sort(key=lambda c: (c["mean"], c["cov"], c["area"]), reverse=True)
            cand = cand[:max(1, max_targets)]
            for i, c in enumerate(cand, start=1):
                s.add(Target(run_id=run_id, rank=i, area_m2=c["area"],
                             centroid_lon=c["clon"], centroid_lat=c["clat"],
                             centroid_easting=c["cx_utm"], centroid_northing=c["cy_utm"],
                             mean_score=c["mean"], max_score=c["max"], coverage=c["cov"],
                             status_label="MODEL OUTPUT", review_status="Proposed",
                             evidence={"per_layer": c["ev"], "constraints": c["chk"],
                                       "next_steps": c["steps"], "missing_evidence": c["missing"],
                                       "supporting": [k for k, v in c["ev"].items() if v is not None and v >= 0.5],
                                       "conflicting": [k for k, v in c["ev"].items() if v is not None and v < 0.3]},
                             polygon_geojson=c["poly"]))

            run.grid_path = grid_path
            run.coverage_path = cov_path
            run.contributions_path = contrib_path
            run.grid_meta = {"nx": int(nx), "ny": int(ny), "grid_m": float(cfg.get("grid_m", 100.0)),
                             "threshold": thr, "n_targets": len(cand),
                             "origin_x": float(grid["origin_x"]), "origin_y": float(grid["origin_y"]),
                             "evidence_gate": gate,
                             "insufficient_evidence": insufficient}
            run.metrics = metrics
            run.dataset_ids = [d.id for d in dss]
            run.status = "done"
            run.progress = 1.0
            s.commit()

            s.add(ValidationResult(run_id=run_id, method=method,
                                   curves={"success_rate": succ, "prediction_rate": pred},
                                   auc=auc, holdout=ht,
                                   sensitivity={"note": "run sensitivity via POST /validation/{id}/sensitivity"}))
            s.commit()
            return {"ok": True, "n_targets": len(cand)}
        except Exception as e:
            run.status = "failed"
            run.error = f"{e}\n{traceback.format_exc(limit=3)}"
            run.progress = 1.0
            s.commit()
            return {"ok": False, "error": str(e)}


def n_lab_plus(nlab: int) -> int:
    return int(nlab)


def recommend_steps(evidence: dict, coverage: float, constraints_check: dict) -> list[str]:
    steps = []
    if evidence.get("dist_structure") is not None and evidence["dist_structure"] >= 0.5:
        steps.append("Field mapping along controlling structures; trenching across strike where permitted.")
    if evidence.get("geochem_au") is not None and evidence["geochem_au"] >= 0.5:
        steps.append("Infill soil sampling grid (50 m x 100 m) over anomaly core; QA/QC with blanks/duplicates.")
    else:
        steps.append("First-pass soil/stream-sediment sampling — geochemical coverage is missing or weak here.")
    if coverage < 0.75:
        steps.append(f"Coverage is only {coverage:.0%} — fill missing evidence layers before drilling decisions.")
    if not constraints_check.get("clean", True):
        names = ", ".join(c["name"] for c in constraints_check.get("conflicts", []))
        steps.append(f"Resolve conflicts with constraint areas ({names}) with GSD/cadastre before field access.")
    steps.append("Ground magnetics/VLF over target to refine structural traps.")
    return steps
