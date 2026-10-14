"""Analysis grid builder. Default 100 m pilot grid in EPSG:32736 over an AOI."""
from __future__ import annotations
import math
import numpy as np
from pyproj import Transformer

_STORAGE_TO_ANALYSIS = Transformer.from_crs("EPSG:4326", "EPSG:32736", always_xy=True)
_ANALYSIS_TO_STORAGE = Transformer.from_crs("EPSG:32736", "EPSG:4326", always_xy=True)


def aoi_bounds_utm(aoi_geojson: dict) -> tuple[float, float, float, float]:
    """Project AOI polygon exterior to UTM36S and return (minx, miny, maxx, maxy)."""
    geom = aoi_geojson.get("geometry", aoi_geojson) if aoi_geojson.get("type") == "Feature" else aoi_geojson
    coords = []
    gtype = geom.get("type")
    if gtype == "Polygon":
        rings = geom["coordinates"]
        coords = rings[0]
    elif gtype == "MultiPolygon":
        for poly in geom["coordinates"]:
            coords.extend(poly[0])
    else:
        raise ValueError(f"AOI must be Polygon/MultiPolygon, got {gtype}")
    xs, ys = [], []
    for lon, lat in coords:
        x, y = _STORAGE_TO_ANALYSIS.transform(float(lon), float(lat))
        xs.append(x)
        ys.append(y)
    return min(xs), min(ys), max(xs), max(ys)


def build_grid(aoi_geojson: dict, grid_m: float = 100.0, max_cells: int = 2_500_000) -> dict:
    """Build a regular analysis grid. Returns grid_meta dict with transform + shape.

    Raises ValueError if grid would exceed max_cells (resource limit).
    """
    if grid_m <= 0:
        raise ValueError("grid_m must be > 0")
    minx, miny, maxx, maxy = aoi_bounds_utm(aoi_geojson)
    nx = max(1, math.ceil((maxx - minx) / grid_m))
    ny = max(1, math.ceil((maxy - miny) / grid_m))
    if nx * ny > max_cells:
        raise ValueError(
            f"Grid {nx}x{ny}={nx*ny:,} cells exceeds limit {max_cells:,}. "
            f"Use a coarser grid_m (current {grid_m} m) or a smaller AOI.")
    xs = minx + (np.arange(nx) + 0.5) * grid_m
    ys = miny + (np.arange(ny) + 0.5) * grid_m
    XX, YY = np.meshgrid(xs, ys)
    lon, lat = _ANALYSIS_TO_STORAGE.transform(XX, YY)
    return {
        "nx": int(nx), "ny": int(ny), "grid_m": float(grid_m),
        "origin_x": float(minx), "origin_y": float(miny),
        "crs_analysis": "EPSG:32736", "crs_storage": "EPSG:4326",
        "grid_x": XX, "grid_y": YY, "grid_lon": np.asarray(lon), "grid_lat": np.asarray(lat),
    }
