"""Prospectivity scoring: weighted overlay + fuzzy logic + coverage.

Rules (non-negotiable):
- Missing data is NOT negative evidence: NaN cells are excluded from the
  weighted mean and counted in a separate coverage layer.
- Scores are relative rankings 0..1, NEVER probability of an economic deposit.
- Deterministic: same inputs + seed -> byte-identical grids (no RNG in these paths;
  seed is stored for any stochastic caller such as RF).
"""
from __future__ import annotations
import numpy as np

CODE_VERSION = "0.1.0"


def _stack(layers: dict[str, np.ndarray]) -> tuple[list[str], np.ndarray]:
    keys = sorted(layers.keys())
    arr = np.stack([np.asarray(layers[k], dtype=float) for k in keys], axis=0)
    return keys, arr


def weighted_overlay(layers: dict[str, np.ndarray], weights: dict[str, float]) -> dict:
    """Weighted mean ignoring NaN. Returns {score, contributions, coverage}."""
    if not layers:
        raise ValueError("no layers supplied")
    keys, arr = _stack(layers)
    w = np.array([float(weights.get(k, 0.0)) for k in keys], dtype=float)
    if (w < 0).any():
        raise ValueError("weights must be >= 0")
    if w.sum() <= 0:
        raise ValueError("weights must sum to > 0")
    w = w / w.sum()
    valid = np.isfinite(arr)
    num = np.nansum(arr * w[:, None, None], axis=0)
    den = (valid * w[:, None, None]).sum(axis=0)
    with np.errstate(invalid="ignore", divide="ignore"):
        score = num / np.where(den > 0, den, np.nan)
    score[den <= 0] = np.nan
    contributions = {k: (np.where(np.isfinite(arr[i]), arr[i] * w[i], np.nan))
                     for i, k in enumerate(keys)}
    coverage = den  # 0..1 fraction of weighted evidence present
    return {"score": np.clip(score, 0, 1), "contributions": contributions,
            "coverage": np.clip(coverage, 0, 1), "weights_used": dict(zip(keys, w.tolist()))}


def fuzzy_overlay(layers: dict[str, np.ndarray], gamma: float = 0.85,
                  operator: str = "gamma") -> dict:
    """Fuzzy AND (min) / OR (max) / gamma combination. Inputs must already be 0..1."""
    if not layers:
        raise ValueError("no layers supplied")
    if not (0.0 <= gamma <= 1.0):
        raise ValueError("gamma must be 0..1")
    keys, arr = _stack(layers)
    if np.nanmin(arr) < -1e-9 or np.nanmax(arr) > 1 + 1e-9:
        raise ValueError("fuzzy inputs must be normalised 0..1 first")
    filled_min = np.where(np.isfinite(arr), arr, 1.0)   # missing = neutral for AND
    filled_max = np.where(np.isfinite(arr), arr, 0.0)   # missing = neutral for OR
    f_and = np.min(filled_min, axis=0)
    f_or = np.max(filled_max, axis=0)
    if operator == "and":
        score = f_and
    elif operator == "or":
        score = f_or
    elif operator == "gamma":
        with np.errstate(invalid="ignore"):
            score = (f_and ** (1 - gamma)) * (f_or ** gamma)
    else:
        raise ValueError(f"unknown fuzzy operator {operator!r}")
    valid = np.isfinite(arr)
    coverage = valid.mean(axis=0)
    return {"score": np.clip(score, 0, 1), "coverage": np.clip(coverage, 0, 1),
            "f_and": f_and, "f_or": f_or, "gamma": gamma, "operator": operator}


def coverage_layer(layers: dict[str, np.ndarray],
                   weights: dict[str, float] | None = None) -> np.ndarray:
    """Fraction of evidence present per cell (unweighted mean or weighted)."""
    keys, arr = _stack(layers)
    valid = np.isfinite(arr).astype(float)
    if weights is None:
        return valid.mean(axis=0)
    w = np.array([float(weights.get(k, 0.0)) for k in keys], dtype=float)
    w = w / w.sum()
    return (valid * w[:, None, None]).sum(axis=0)
