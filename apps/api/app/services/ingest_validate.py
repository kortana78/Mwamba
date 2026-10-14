"""Ingest service: parse uploads, validate honestly, store with provenance."""
from __future__ import annotations
import csv
import io
import json
import os
import sys

try:
    from mwamba_geo.validate import validate_geojson, validate_csv  # noqa: E402
    from mwamba_geo.crs import SUPPORTED_CRS, log_reprojection  # noqa: E402
except ImportError:  # local checkout without installed package
    sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "..", "..", "packages", "geo"))
    from mwamba_geo.validate import validate_geojson, validate_csv  # noqa: E402
    from mwamba_geo.crs import SUPPORTED_CRS, log_reprojection  # noqa: E402

from ..config import settings

#: Malawi UTM36S envelope (metres) used to disambiguate projected uploads:
#: WGS84/UTM36S vs Arc1950/UTM36S overlap heavily; Arc1950 is ~300 m SW of WGS84.
UTM36S_ENVELOPE = (500000.0, 8500000.0, 800000.0, 8950000.0)


def looks_projected(values: list[float]) -> bool:
    """Heuristic: coordinate magnitudes in the hundreds of thousands = metres."""
    return any(abs(v) > 180 for v in values)


def detect_projected_crs(xs: list[float], ys: list[float]) -> str | None:
    """Return 'EPSG:32736' or 'EPSG:20936' when coords plausibly fall in the
    Malawi UTM36S envelope, else None (caller must ask the user — never guess)."""
    if not xs or not ys:
        return None
    x0, y0, x1, y1 = UTM36S_ENVELOPE
    in_wgs = sum(1 for x, y in zip(xs, ys) if x0 <= x <= x1 and y0 <= y <= y1) / len(xs)
    if in_wgs < 0.8:
        return None
    # Arc1950 datum ≈ 300 m from WGS84 at same lat/lon; test which frame puts the
    # centroid inside the Malawi lon/lat bbox.
    from pyproj import Transformer
    cx, cy = sum(xs) / len(xs), sum(ys) / len(ys)
    for epsg in ("EPSG:32736", "EPSG:20936"):
        t = Transformer.from_crs(epsg, "EPSG:4326", always_xy=True)
        lon, lat = t.transform(cx, cy)
        if 32.6 <= lon <= 35.9 and -17.2 <= lat <= -9.3:
            return epsg
    return None


def reproject_feature_coords(obj: dict, src_crs: str) -> dict:
    """Transform all Point/LineString/Polygon coordinates src -> EPSG:4326."""
    from pyproj import Transformer
    t = Transformer.from_crs(src_crs, "EPSG:4326", always_xy=True)

    def _xy(pt):
        x, y = t.transform(float(pt[0]), float(pt[1]))
        return [x, y] + list(pt[2:])

    def _geom(g):
        gt = (g or {}).get("type")
        if gt == "Point":
            g["coordinates"] = _xy(g["coordinates"])
        elif gt in ("LineString", "MultiPoint"):
            g["coordinates"] = [_xy(p) for p in g["coordinates"]]
        elif gt in ("Polygon", "MultiLineString"):
            g["coordinates"] = [[_xy(p) for p in ring] for ring in g["coordinates"]]
        elif gt == "MultiPolygon":
            g["coordinates"] = [[[_xy(p) for p in ring] for ring in poly] for poly in g["coordinates"]]
        return g

    for f in obj.get("features", []):
        f["geometry"] = _geom(f.get("geometry") or {})
    return obj


def check_upload_size(n_bytes: int) -> None:
    limit = settings.max_upload_mb() * 1024 * 1024
    if n_bytes > limit:
        raise ValueError(f"Upload {n_bytes/1e6:.1f} MB exceeds limit {settings.max_upload_mb()} MB")


def ingest_geojson_bytes(raw: bytes, *, kind: str, value_field: str | None = None,
                          crs_declared: str = "EPSG:4326") -> tuple[dict, dict, int]:
    """Returns (feature_collection, quality_report, feature_count).

    crs_declared="auto": metre-range coordinates are tested against the Malawi
    UTM36S envelope (EPSG:32736 vs Arc1950 EPSG:20936) and transformed with a
    logged processing step. Anything else ambiguous raises — the user is asked,
    never guessed for.
    """
    check_upload_size(len(raw))
    auto = crs_declared.lower() == "auto"
    if not auto and crs_declared.upper() not in SUPPORTED_CRS:
        raise ValueError(f"Unknown CRS {crs_declared}. Supported: {sorted(SUPPORTED_CRS)} + 'auto'")
    try:
        obj = json.loads(raw.decode("utf-8"))
    except Exception as e:
        raise ValueError(f"Invalid JSON: {e}")
    history: list = []
    effective_crs = crs_declared.upper() if not auto else "EPSG:4326"
    if auto:
        xs, ys = _sample_coords(obj)
        if looks_projected(xs + ys):
            hit = detect_projected_crs(xs, ys)
            if hit is None:
                raise ValueError(
                    "Coordinates look projected (metre range) but fall outside the Malawi "
                    "UTM36S envelope for both EPSG:32736 and EPSG:20936. "
                    "Declare the CRS explicitly (crs_original).")
            obj = reproject_feature_coords(obj, hit)
            effective_crs = hit
            log_reprojection(history, hit, "EPSG:4326", len(obj.get("features", [])))
        # else: plain degrees, nothing to do
    quality = validate_geojson(obj, kind=kind, value_field=value_field)
    if effective_crs != "EPSG:4326":
        obj = reproject_feature_coords(obj, effective_crs)
        log_reprojection(history, effective_crs, "EPSG:4326", len(obj.get("features", [])))
        # re-validate post-transform so Malawi-bounds/duplicates reflect true positions
        quality = validate_geojson(obj, kind=kind, value_field=value_field)
    elif auto:
        quality.setdefault("warnings", []).append("CRS auto-detect: degree-range coordinates, kept as EPSG:4326.")
    else:
        quality.setdefault("warnings", []).append(
            f"Declared CRS {effective_crs}: coordinates reprojected to EPSG:4326 on ingest (logged).")
    quality["crs_detected"] = effective_crs
    quality["processing_history"] = history
    return obj, quality, len(obj.get("features", []))


def _sample_coords(obj: dict, limit: int = 200) -> tuple[list[float], list[float]]:
    xs, ys = [], []

    def _walk(coords, depth):
        if depth == 0:
            try:
                xs.append(float(coords[0]))
                ys.append(float(coords[1]))
            except (ValueError, TypeError, IndexError):
                pass
            return
        for c in coords:
            if len(xs) >= limit:
                return
            _walk(c, depth - 1)

    depth_of = {"Point": 0, "MultiPoint": 1, "LineString": 1, "MultiLineString": 2,
                "Polygon": 2, "MultiPolygon": 3}
    for f in (obj.get("features", [])[:limit]):
        g = f.get("geometry") or {}
        d = depth_of.get(g.get("type", ""), None)
        if d is not None:
            _walk(g.get("coordinates", []), d)
    return xs, ys


def ingest_csv_text(text: str, *, lon_field: str = "lon", lat_field: str = "lat",
                    value_field: str | None = "Au_ppb") -> tuple[list[dict], dict]:
    check_upload_size(len(text.encode("utf-8")))
    quality = validate_csv(text, lon_field=lon_field, lat_field=lat_field, value_field=value_field)
    reader = csv.DictReader(io.StringIO(text))
    rows = list(reader)
    return rows, quality


def to_points_geojson(rows: list[dict], lon_field: str, lat_field: str) -> dict:
    feats = []
    for r in rows:
        try:
            lon = float(str(r[lon_field]).strip())
            lat = float(str(r[lat_field]).strip())
        except (ValueError, TypeError):
            continue
        feats.append({"type": "Feature",
                      "geometry": {"type": "Point", "coordinates": [lon, lat]},
                      "properties": {k: v for k, v in r.items() if k not in (lon_field, lat_field)}})
    return {"type": "FeatureCollection", "features": feats}
