"""GeoTIFF/COG ingest (rasterio): validate CRS, nodata, resolution, extent vs
Malawi; store + register with provenance. Map serving = PNG data-URL + bounds
(hillshade for DEMs), no TiTiler required."""
from __future__ import annotations
import base64
import io
import os

import numpy as np

MALAWI_BBOX = (32.6, -17.2, 35.9, -9.3)


def validate_geotiff(raw: bytes, max_mb: int = 100) -> tuple[dict, dict]:
    """Returns (stats, quality). Raises ValueError with plain messages."""
    import rasterio
    from rasterio.io import MemoryFile
    if len(raw) > max_mb * 1024 * 1024:
        raise ValueError(f"GeoTIFF {len(raw)/1e6:.1f} MB exceeds {max_mb} MB limit")
    try:
        mem = MemoryFile(raw)
        src = mem.open()
    except Exception as e:
        raise ValueError(f"Not a readable GeoTIFF: {e}")
    with src:
        if src.crs is None:
            raise ValueError("GeoTIFF has no CRS. Re-export with a declared CRS (e.g. EPSG:4326).")
        try:
            epsg = src.crs.to_epsg() or 0
        except Exception:
            epsg = 0
        from rasterio.warp import transform_bounds
        try:
            w, s, e, n = transform_bounds(src.crs, "EPSG:4326",
                                          *src.bounds, densify_pts=21)
        except Exception as ex:
            raise ValueError(f"Cannot interpret CRS {src.crs}: {ex}")
        m0, n0, m1, n1 = MALAWI_BBOX
        overlaps = not (e < m0 or w > m1 or n < n0 or s > n1)
        resx = abs(src.transform.a)
        # resolution in metres (approx; exact when projected)
        res_m = resx * 111320.0 if src.crs.is_geographic else resx
        sample = src.read(1, out_shape=(min(512, src.height), min(512, src.width)))
        stats = {
            "crs": str(src.crs), "epsg": epsg, "width": src.width, "height": src.height,
            "count": src.count, "dtype": str(src.dtypes[0]), "nodata": src.nodata,
            "resolution_m_approx": round(float(res_m), 2),
            "bounds_4326": [round(v, 5) for v in (w, s, e, n)],
            "overlaps_malawi": overlaps,
            "tiled": bool(src.profile.get("tiled")),
            "compress": str(src.profile.get("compress") or "none"),
        }
        errors, warnings = [], []
        if not overlaps:
            errors.append(f"Raster extent {stats['bounds_4326']} does not overlap Malawi {MALAWI_BBOX}")
        if src.nodata is None:
            warnings.append("No nodata value set; zeros may be misread as data")
        finite = sample[np.isfinite(sample)]
        if finite.size:
            stats.update({"sample_min": float(finite.min()), "sample_max": float(finite.max()),
                          "sample_mean": float(finite.mean())})
        return stats, {"ok": len(errors) == 0, "errors": errors, "warnings": warnings,
                       "stats": stats}


def hillshade_png(raw: bytes, *, max_px: int = 800, azimuth: float = 315.0,
                  altitude: float = 45.0) -> tuple[str, list]:
    """Render a DEM GeoTIFF to a PNG data-URL + lon/lat bounds for map overlay."""
    import rasterio
    from rasterio.io import MemoryFile
    from rasterio.warp import transform_bounds
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    with MemoryFile(raw).open() as src:
        scale = max(1, int(max(src.height, src.width) / max_px))
        arr = src.read(1, out_shape=(src.height // scale, src.width // scale),
                       resampling=rasterio.enums.Resampling.bilinear)
        resx = abs(src.transform.a) * scale
        resy = abs(src.transform.e) * scale
        if src.crs.is_geographic:
            resx *= 111320.0
            resy *= 111320.0
        nodata = src.nodata
        z = arr.astype(float)
        if nodata is not None:
            z[z == nodata] = np.nan
        gy, gx = np.gradient(np.nan_to_num(z, nan=np.nanmean(z)), resy, resx)
        az, alt = np.radians(360 - azimuth + 90) % (2 * np.pi), np.radians(altitude)
        slope = np.pi / 2 - np.arctan(np.hypot(gx, gy))
        aspect = np.arctan2(-gx, gy)
        hs = (np.sin(alt) * np.sin(slope)
              + np.cos(alt) * np.cos(slope) * np.cos(az - aspect))
        hs = np.clip(hs, 0, 1)
        bounds = list(transform_bounds(src.crs, "EPSG:4326", *src.bounds, densify_pts=21))
    fig, ax = plt.subplots(figsize=(6, 6), dpi=110)
    ax.imshow(hs, cmap="gray", vmin=0, vmax=1)
    ax.axis("off")
    buf = io.BytesIO()
    fig.savefig(buf, format="png", bbox_inches="tight", pad_inches=0)
    plt.close(fig)
    return ("data:image/png;base64," + base64.b64encode(buf.getvalue()).decode(),
            [round(v, 5) for v in bounds])


def slope_stats_utm(raw: bytes) -> dict:
    """Mean/max slope info for the engine's dem_slope evidence recipe."""
    import rasterio
    from rasterio.io import MemoryFile
    with MemoryFile(raw).open() as src:
        scale = max(1, int(max(src.height, src.width) / 256))
        arr = src.read(1, out_shape=(src.height // scale, src.width // scale),
                       resampling=rasterio.enums.Resampling.bilinear).astype(float)
        if src.nodata is not None:
            arr[arr == src.nodata] = np.nan
        resx = abs(src.transform.a) * scale
        resy = abs(src.transform.e) * scale
        if src.crs.is_geographic:
            resx *= 111320.0
            resy *= 111320.0
        gy, gx = np.gradient(np.nan_to_num(arr, nan=np.nanmean(arr)), resy, resx)
        slope_deg = np.degrees(np.arctan(np.hypot(gx, gy)))
        finite = slope_deg[np.isfinite(slope_deg)]
        return {"mean_slope_deg": round(float(finite.mean()), 2),
                "p90_slope_deg": round(float(np.percentile(finite, 90)), 2),
                "resolution_m": round(float((resx + resy) / 2), 1)}


def sentinel2_ratios_from_multiband(raw: bytes, band_map: dict,
                                    max_px: int = 1024) -> tuple[dict, dict]:
    """Band math on a multiband Sentinel-2 GeoTIFF.

    band_map: {"B2": idx1based, "B4": .., "B8": .., "B11": .., "B12": ..}.
    Returns (arrays4, quality) with iron_oxide (B4/B2), clay (B11/B12), ndvi
    and vegetation mask. Arrays are downsampled to max_px for the pilot build.
    """
    import sys as _sys
    import os as _os
    try:
        from mwamba_geo.features import sentinel2_ratios as _ratios  # noqa: E402
    except ImportError:
        _sys.path.insert(0, _os.path.join(_os.path.dirname(__file__), "..", "..", "..", "..", "packages", "geo"))
        from mwamba_geo.features import sentinel2_ratios as _ratios  # noqa: E402
    import rasterio
    from rasterio.io import MemoryFile
    try:
        mem = MemoryFile(raw)
        src = mem.open()
    except Exception as e:
        raise ValueError(f"Not a readable GeoTIFF: {e}")
    with src:
        need = {"B2", "B4", "B8", "B11", "B12"}
        if set(band_map) < need:
            raise ValueError(f"band_map must name {sorted(need)} (got {sorted(band_map)})")
        if src.count < max(band_map.values()):
            raise ValueError(f"GeoTIFF has {src.count} bands but band_map needs {max(band_map.values())}")
        scale = max(1, int(max(src.height, src.width) / max_px))
        oh, ow = src.height // scale, src.width // scale
        bands = {}
        for name, idx in band_map.items():
            a = src.read(int(idx), out_shape=(oh, ow),
                         resampling=rasterio.enums.Resampling.bilinear).astype(float)
            if src.nodata is not None:
                a[a == src.nodata] = np.nan
            a[a <= 0] = np.nan  # S2 reflectance must be positive; zeros are nodata fill
            bands[name] = a
        r = _ratios(bands["B2"], bands["B4"], bands["B8"], bands["B11"], bands["B12"])
        stats = {}
        for k in ("iron_oxide", "clay", "ndvi"):
            f = r[k][np.isfinite(r[k])]
            stats[k] = {"mean": round(float(f.mean()), 4) if f.size else None,
                        "p90": round(float(np.percentile(f, 90)), 4) if f.size else None,
                        "coverage": round(float(np.isfinite(r[k]).sum() / r[k].size), 4)}
        stats["veg_fraction"] = round(float(r["vegetation_mask"].sum() / r["vegetation_mask"].size), 4)
        dst_transform = src.transform @ src.transform.scale(scale, scale)
        meta = {"crs": str(src.crs), "width": ow, "height": oh,
                "source_bands": band_map, "scale": scale,
                "transform": list(dst_transform)[:6],
                "bounds_4326": None}
        try:
            from rasterio.warp import transform_bounds as _tb
            meta["bounds_4326"] = [round(v, 5) for v in
                                   _tb(src.crs, "EPSG:4326", *src.bounds, densify_pts=21)]
        except Exception:
            pass
    return {"arrays": r, "meta": meta}, {"ok": True, "errors": [], "warnings": [], "stats": stats}


def write_single_band_geotiff(array: np.ndarray, *, crs: str, transform,
                              nodata: float = float("nan")) -> bytes:
    """Encode a float32 single-band GeoTIFF from an array + georeferencing."""
    import io as _io
    import rasterio
    from rasterio.io import MemoryFile
    h, w = array.shape
    prof = {"driver": "GTiff", "height": h, "width": w, "count": 1,
            "dtype": "float32", "crs": crs, "transform": transform,
            "nodata": nodata, "compress": "deflate"}
    buf = _io.BytesIO()
    with MemoryFile() as mem:
        with mem.open(**prof) as dst:
            dst.write(np.asarray(array, dtype=np.float32), 1)
        buf.write(mem.read())
    return buf.getvalue()
