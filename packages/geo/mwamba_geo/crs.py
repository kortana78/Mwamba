"""CRS conventions for Malawi. Storage EPSG:4326, analysis EPSG:32736 (WGS84/UTM 36S).

Legacy Malawian maps are often in Arc 1950 / UTM 36S (EPSG:20936) or Arc 1950
geographic (EPSG:4209). Every reprojection must be logged to the dataset's
processing history via log_reprojection().
"""
from __future__ import annotations
import datetime as _dt
from pyproj import Transformer, CRS

MALAWI_CRS_STORAGE = "EPSG:4326"
MALAWI_CRS_ANALYSIS = "EPSG:32736"
MALAWI_CRS_ARC1950_UTM36S = "EPSG:20936"
MALAWI_CRS_ARC1950_GEO = "EPSG:4209"
# (min_lon, min_lat, max_lon, max_lat)
MALAWI_BBOX = (32.6, -17.2, 35.9, -9.3)

SUPPORTED_CRS = {
    "EPSG:4326": "WGS 84 geographic (storage CRS)",
    "EPSG:32736": "WGS 84 / UTM zone 36S (analysis CRS)",
    "EPSG:20936": "Arc 1950 / UTM zone 36S (legacy Malawi maps)",
    "EPSG:4209": "Arc 1950 geographic (legacy)",
}

_transformers: dict[tuple[str, str], Transformer] = {}


def _get_transformer(src: str, dst: str) -> Transformer:
    key = (src.upper(), dst.upper())
    if key not in _transformers:
        _transformers[key] = Transformer.from_crs(CRS(src), CRS(dst), always_xy=True)
    return _transformers[key]


def reproject_point(lon: float, lat: float, src: str, dst: str) -> tuple[float, float]:
    """Reproject a single (lon/x, lat/y) point. Raises on unknown CRS."""
    src_u, dst_u = src.upper(), dst.upper()
    if src_u not in SUPPORTED_CRS:
        raise ValueError(f"Unsupported source CRS {src}. Supported: {sorted(SUPPORTED_CRS)}")
    if dst_u not in SUPPORTED_CRS:
        raise ValueError(f"Unsupported target CRS {dst}. Supported: {sorted(SUPPORTED_CRS)}")
    if src_u == dst_u:
        return lon, lat
    t = _get_transformer(src_u, dst_u)
    x, y = t.transform(lon, lat)
    return float(x), float(y)


def reproject_ring(ring: list, src: str, dst: str) -> list:
    return [list(reproject_point(float(x), float(y), src, dst)) for x, y in ring]


def in_malawi(lon: float, lat: float) -> bool:
    minx, miny, maxx, maxy = MALAWI_BBOX
    return (minx <= lon <= maxx) and (miny <= lat <= maxy)


def log_reprojection(history: list, src: str, dst: str, n_features: int, code_version: str = "0.1.0") -> list:
    """Append a reprojection entry to a dataset processing-history list. Never guess silently."""
    entry = {
        "step": "reproject",
        "from_crs": src.upper(),
        "to_crs": dst.upper(),
        "n_features": n_features,
        "code_version": code_version,
        "at": _dt.datetime.now(_dt.timezone.utc).isoformat(),
    }
    history.append(entry)
    return history
