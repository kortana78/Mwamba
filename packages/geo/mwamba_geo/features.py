"""Feature engineering: documented, regenerable evidence-layer transforms.

Each function maps inputs -> a normalised 0..1 evidence grid aligned to the
analysis grid, plus a NaN mask where data is absent (missing != negative).
Every derived layer stores its recipe (inputs, params, code version).
"""
from __future__ import annotations
import numpy as np

CODE_VERSION = "0.1.0"


def _as_float(a: np.ndarray) -> np.ndarray:
    return np.asarray(a, dtype=float)


def distance_decay(distance_m: np.ndarray, decay_m: float = 1500.0) -> np.ndarray:
    """Exponential decay favourability from distance-to-structure (0..1, 1 at structure)."""
    d = _as_float(distance_m)
    out = np.exp(-d / float(decay_m))
    out = np.clip(out, 0.0, 1.0)
    out[~np.isfinite(d)] = np.nan
    return out


def min_distance_to_segments(gx: np.ndarray, gy: np.ndarray,
                             segments: list[tuple[float, float, float, float]]) -> np.ndarray:
    """Min Euclidean distance (m) from each grid cell to a set of line segments in UTM."""
    gx = _as_float(gx)
    gy = _as_float(gy)
    if not segments:
        return np.full_like(gx, np.nan)
    best = np.full_like(gx, np.inf)
    for (x1, y1, x2, y2) in segments:
        dx, dy = x2 - x1, y2 - y1
        L2 = dx * dx + dy * dy
        if L2 == 0:
            d = np.hypot(gx - x1, gy - y1)
        else:
            t = np.clip(((gx - x1) * dx + (gy - y1) * dy) / L2, 0.0, 1.0)
            d = np.hypot(gx - (x1 + t * dx), gy - (y1 + t * dy))
        best = np.minimum(best, d)
    return best


def fault_density(gx: np.ndarray, gy: np.ndarray,
                  fault_points: np.ndarray, radius_m: float = 2000.0) -> np.ndarray:
    """Gaussian-kernel fault density normalised 0..1 (NaN where no faults within 3*radius)."""
    gx = _as_float(gx)
    gy = _as_float(gy)
    fp = np.asarray(fault_points, dtype=float).reshape(-1, 2)
    if len(fp) == 0:
        return np.full_like(gx, np.nan)
    # coarse but deterministic: sum of gaussian kernels
    dens = np.zeros_like(gx)
    for (fx, fy) in fp:
        d2 = (gx - fx) ** 2 + (gy - fy) ** 2
        dens += np.exp(-d2 / (2.0 * radius_m ** 2))
    cap = float(np.nanpercentile(dens, 98)) or 1.0
    out = np.clip(dens / cap, 0.0, 1.0)
    out[dens <= 1e-6] = np.nan  # absent, not zero-evidence
    return out


def lithology_score(mask_per_unit: dict[str, np.ndarray],
                    scores: dict[str, float]) -> np.ndarray:
    """Combine boolean unit masks with user-assigned favourability scores (0..1)."""
    keys = list(mask_per_unit.keys())
    if not keys:
        raise ValueError("no lithology units supplied")
    shape = np.shape(next(iter(mask_per_unit.values())))
    out = np.full(shape, np.nan)
    for unit, mask in mask_per_unit.items():
        s = float(scores.get(unit, 0.0))
        if not (0.0 <= s <= 1.0):
            raise ValueError(f"lithology score for {unit!r} must be 0..1, got {s}")
        m = np.asarray(mask, dtype=bool)
        out[m] = s
    return out


def idw_interpolation(gx: np.ndarray, gy: np.ndarray, px: np.ndarray, py: np.ndarray,
                      values: np.ndarray, power: float = 2.0,
                      nodata_radius_m: float | None = None) -> np.ndarray:
    """Inverse-distance-weighted interpolation. Warn on sparse data via NaN mask.

    nodata_radius_m: cells farther than this from every sample -> NaN (missing data).
    """
    gx, gy = _as_float(gx), _as_float(gy)
    px, py, values = (np.asarray(a, dtype=float) for a in (px, py, values))
    if len(px) == 0:
        return np.full_like(gx, np.nan)
    out = np.zeros_like(gx)
    wsum = np.zeros_like(gx)
    for x, y, v in zip(px, py, values):
        if not np.isfinite(v):
            continue
        d = np.hypot(gx - x, gy - y)
        d = np.maximum(d, 1e-6)
        w = 1.0 / (d ** power)
        out += w * v
        wsum += w
    with np.errstate(invalid="ignore", divide="ignore"):
        out = out / np.maximum(wsum, 1e-12)
    out[wsum <= 0] = np.nan
    if nodata_radius_m is not None:
        mind = np.full_like(gx, np.inf)
        for x, y in zip(px, py):
            mind = np.minimum(mind, np.hypot(gx - x, gy - y))
        out[mind > nodata_radius_m] = np.nan
    return out


def robust_anomaly_threshold(values: np.ndarray, k_mad: float = 5.0) -> dict:
    """Background/anomaly threshold via median + k*MAD (+ percentiles). Pure computed stats."""
    v = np.asarray(values, dtype=float)
    v = v[np.isfinite(v)]
    if len(v) == 0:
        return {"median": None, "mad": None, "threshold": None, "p90": None, "p95": None, "n": 0}
    med = float(np.median(v))
    mad = float(np.median(np.abs(v - med)))
    return {"median": med, "mad": mad, "threshold": med + k_mad * mad,
            "p90": float(np.percentile(v, 90)), "p95": float(np.percentile(v, 95)), "n": int(len(v))}


def normalise_01(a: np.ndarray, *, pmin: float = 2.0, pmax: float = 98.0) -> np.ndarray:
    """Percentile-stretch normalisation to 0..1, preserving NaN (missing data)."""
    a = _as_float(a)
    lo = float(np.nanpercentile(a, pmin))
    hi = float(np.nanpercentile(a, pmax))
    if not np.isfinite(lo) or not np.isfinite(hi) or hi <= lo:
        out = np.full_like(a, np.nan)
        finite = np.isfinite(a)
        out[finite] = 0.5
        return out
    return np.clip((a - lo) / (hi - lo), 0.0, 1.0)


def recipe(inputs: list[str], params: dict, func_name: str) -> dict:
    return {"function": func_name, "inputs": inputs, "params": params, "code_version": CODE_VERSION}


def hillshade_array(dem: np.ndarray, dx: float, dy: float,
                    azimuth_deg: float = 315.0, altitude_deg: float = 45.0) -> np.ndarray:
    """Hillshade 0..1 from an elevation grid (NaN preserved). Deterministic."""
    z = _as_float(dem)
    filled = np.nan_to_num(z, nan=np.nanmean(z))
    gy, gx = np.gradient(filled, dy, dx)
    az = np.radians((360.0 - float(azimuth_deg) + 90.0) % 360.0)
    alt = np.radians(float(altitude_deg))
    slope = np.pi / 2.0 - np.arctan(np.hypot(gx, gy))
    aspect = np.arctan2(-gx, gy)
    hs = (np.sin(alt) * np.sin(slope)
          + np.cos(alt) * np.cos(slope) * np.cos(az - aspect))
    hs = np.clip(hs, 0.0, 1.0)
    hs[~np.isfinite(z)] = np.nan
    return hs


def extract_lineaments(dem_grid: np.ndarray, gx: np.ndarray, gy: np.ndarray,
                       grid_m: float, *, azimuths: tuple = (0.0, 45.0, 90.0, 135.0),
                       edge_percentile: float = 90.0,
                       min_length_m: float = 500.0) -> dict:
    """Multi-azimuth hillshade lineaments (unverified structural proxy).

    1. hillshade at each azimuth, 2. Sobel edge magnitude per azimuth,
    3. max across azimuths, 4. percentile threshold, 5. connected components
    filtered by length, 6. PCA stick per component -> UTM segment.
    Deterministic: no randomness, fixed azimuth set.
    """
    from scipy import ndimage
    z = _as_float(dem_grid)
    gm = float(grid_m)
    filled = np.nan_to_num(z, nan=np.nanmean(z))
    edge_max = np.zeros_like(z)
    for az in azimuths:
        hs = hillshade_array(filled, gm, gm, azimuth_deg=float(az))
        sx = ndimage.sobel(np.nan_to_num(hs, nan=np.nanmean(hs)), axis=1)
        sy = ndimage.sobel(np.nan_to_num(hs, nan=np.nanmean(hs)), axis=0)
        edge_max = np.maximum(edge_max, np.hypot(sx, sy))
    edge_max[~np.isfinite(z)] = np.nan
    finite = edge_max[np.isfinite(edge_max)]
    thr = float(np.percentile(finite, edge_percentile)) if finite.size else 0.0
    binary = np.isfinite(edge_max) & (edge_max >= thr)
    labelled, nlab = ndimage.label(binary)
    min_px = max(3, int(float(min_length_m) / gm))
    segments: list[tuple[float, float, float, float]] = []
    for lab in range(1, int(nlab) + 1):
        sel = labelled == lab
        if int(sel.sum()) < min_px:
            continue
        xs = _as_float(gx[sel])
        ys = _as_float(gy[sel])
        mx, my = float(xs.mean()), float(ys.mean())
        xc, yc = xs - mx, ys - my
        cxx, cyy, cxy = float((xc * xc).sum()), float((yc * yc).sum()), float((xc * yc).sum())
        ang = 0.5 * np.arctan2(2.0 * cxy, cxx - cyy)
        dx, dy = float(np.cos(ang)), float(np.sin(ang))
        proj = xc * dx + yc * dy
        half = float(np.abs(proj).max())
        segments.append((mx - dx * half, my - dy * half, mx + dx * half, my + dy * half))
    # deterministic order: longest first
    segments.sort(key=lambda s: -((s[2] - s[0]) ** 2 + (s[3] - s[1]) ** 2))
    return {"segments": segments, "edge_strength": edge_max, "binary": binary,
            "threshold": thr, "n_components": int(nlab), "n_lineaments": len(segments)}


def line_intersections(segments: list[tuple[float, float, float, float]]) -> np.ndarray:
    """Pairwise segment intersections -> (N,2) UTM points. Deterministic."""
    pts: list[list[float]] = []
    n = len(segments)
    for i in range(n):
        x1, y1, x2, y2 = segments[i]
        for j in range(i + 1, n):
            x3, y3, x4, y4 = segments[j]
            den = (x1 - x2) * (y3 - y4) - (y1 - y2) * (x3 - x4)
            if abs(den) < 1e-9:
                continue
            t = ((x1 - x3) * (y3 - y4) - (y1 - y3) * (x3 - x4)) / den
            u = -((x1 - x2) * (y1 - y3) - (y1 - y2) * (x1 - x3)) / den
            if 0.0 <= t <= 1.0 and 0.0 <= u <= 1.0:
                pts.append([x1 + t * (x2 - x1), y1 + t * (y2 - y1)])
    if not pts:
        return np.zeros((0, 2))
    return np.array(pts, dtype=float)


def dem_drainage(dem_grid: np.ndarray, gx: np.ndarray, gy: np.ndarray,
                 grid_m: float, *, accum_percentile: float = 90.0) -> dict:
    """D8 flow accumulation drainage (unverified structural/hydrology proxy).

    Steepest-descent D8 on the raw DEM (no pit filling — sinks stay sinks and
    simply terminate). Deterministic.
    """
    z = _as_float(dem_grid)
    filled = np.nan_to_num(z, nan=np.nanmean(z))
    ny, nx = filled.shape
    # neighbour offsets (E, W, S, N, SE, SW, NE, NW) with distances
    gm = float(grid_m)
    offs = [(0, 1, gm), (0, -1, gm), (1, 0, gm), (-1, 0, gm),
            (1, 1, gm * 1.41421356), (1, -1, gm * 1.41421356),
            (-1, 1, gm * 1.41421356), (-1, -1, gm * 1.41421356)]
    recv_i = np.full((ny, nx), -1, dtype=int)
    recv_j = np.full((ny, nx), -1, dtype=int)
    for iy in range(ny):
        for jx in range(nx):
            best_drop, bi, bj = 0.0, -1, -1
            for di, dj, dist in offs:
                ii, jj = iy + di, jx + dj
                if 0 <= ii < ny and 0 <= jj < nx:
                    drop = (filled[iy, jx] - filled[ii, jj]) / dist
                    if drop > best_drop:
                        best_drop, bi, bj = drop, ii, jj
            recv_i[iy, jx], recv_j[iy, jx] = bi, bj
    accum = np.ones((ny, nx))
    order = np.argsort(filled.ravel())[::-1]
    ri, rj = recv_i.ravel(), recv_j.ravel()
    acc = accum.ravel()
    for k in order:
        i2, j2 = int(ri[k]), int(rj[k])
        if i2 >= 0:
            acc[i2 * nx + j2] += acc[k]
    accum = acc.reshape(ny, nx)
    accum[~np.isfinite(z)] = np.nan
    finite = accum[np.isfinite(accum)]
    thr = float(np.percentile(finite, accum_percentile)) if finite.size else 0.0
    mask = np.isfinite(accum) & (accum >= thr)
    segments: list[tuple[float, float, float, float]] = []
    ys, xs = np.where(mask)
    for iy, jx in zip(ys.tolist(), xs.tolist()):
        i2, j2 = int(recv_i[iy, jx]), int(recv_j[iy, jx])
        if i2 < 0:
            continue
        segments.append((float(gx[iy, jx]), float(gy[iy, jx]),
                         float(gx[i2, j2]), float(gy[i2, j2])))
    return {"accumulation": accum, "mask": mask, "segments": segments,
            "threshold": thr}


def drainage_density_layer(accumulation: np.ndarray, mask: np.ndarray) -> np.ndarray:
    """Normalised log-accumulation 0..1 inside the drainage mask, NaN outside."""
    acc = _as_float(accumulation)
    out = np.full_like(acc, np.nan)
    m = np.asarray(mask, dtype=bool) & np.isfinite(acc) & (acc > 0)
    if not m.any():
        return out
    out[m] = normalise_01(np.log10(np.maximum(acc[m], 1.0)))
    return out


def sentinel2_ratios(b2: np.ndarray, b4: np.ndarray, b8: np.ndarray,
                     b11: np.ndarray, b12: np.ndarray,
                     *, ndvi_veg_threshold: float = 0.4) -> dict:
    """Sentinel-2 alteration proxies (all deterministic, NaN-safe).

    iron_oxide = B4/B2, clay_hydroxyl = B11/B12, ndvi = (B8-B4)/(B8+B4).
    alteration_mask: finite ratios with vegetation masked out.
    """
    b2, b4, b8 = (_as_float(a) for a in (b2, b4, b8))
    b11, b12 = (_as_float(a) for a in (b11, b12))
    with np.errstate(invalid="ignore", divide="ignore"):
        iron = np.where(b2 > 0, b4 / np.maximum(b2, 1e-9), np.nan)
        clay = np.where(b12 > 0, b11 / np.maximum(b12, 1e-9), np.nan)
        ndvi = (b8 - b4) / np.maximum(b8 + b4, 1e-9)
    for a in (iron, clay, ndvi):
        a[~np.isfinite(a)] = np.nan
    veg = np.isfinite(ndvi) & (ndvi > float(ndvi_veg_threshold))
    ok = np.isfinite(iron) & np.isfinite(clay) & (~veg)
    mask = np.where(ok, 1.0, np.nan)
    return {"iron_oxide": iron, "clay": clay, "ndvi": ndvi,
            "vegetation_mask": veg, "alteration_mask": mask}
