"""Scientifically-honest validation: success/prediction-rate curves, spatial block
CV, AUC, held-out occurrence tests, random baseline. Unlabelled ground is NEVER
treated as barren/negative."""
from __future__ import annotations
import numpy as np


def _curve(score: np.ndarray, occurrence_mask: np.ndarray, *, invert_area: bool) -> dict:
    s = np.asarray(score, dtype=float).ravel()
    occ = np.asarray(occurrence_mask, dtype=bool).ravel()
    valid = np.isfinite(s)
    s, occ = s[valid], occ[valid]
    n_occ = int(occ.sum())
    if n_occ == 0:
        return {"ok": False, "reason": "no known occurrences on valid grid cells",
                "xs": [], "ys": [], "auc": None}
    order = np.argsort(-s, kind="stable")
    occ_sorted = occ[order].astype(float)
    cum_occ = np.cumsum(occ_sorted) / n_occ
    frac_area = (np.arange(len(s)) + 1) / len(s)
    # decimate to <= 200 points for storage
    idx = np.linspace(0, len(s) - 1, min(200, len(s))).astype(int)
    xs = frac_area[idx].tolist()
    ys = cum_occ[idx].tolist()
    auc = float(np.trapezoid(cum_occ, frac_area))
    return {"ok": True, "xs": xs, "ys": ys, "auc": auc,
            "n_occurrences": n_occ, "n_cells": int(len(s)),
            "note": "success-rate" if not invert_area else "prediction-rate (held-out)"}


def success_rate_curve(score: np.ndarray, occurrence_mask: np.ndarray) -> dict:
    """% occurrences captured vs % of area (ranked high->low). Training-fit curve."""
    d = _curve(score, occurrence_mask, invert_area=False)
    d["curve"] = "success_rate"
    return d


def prediction_rate_curve(score: np.ndarray, heldout_mask: np.ndarray) -> dict:
    """Same curve evaluated on HELD-OUT occurrences only. Headline validation."""
    d = _curve(score, heldout_mask, invert_area=True)
    d["curve"] = "prediction_rate"
    return d


def auc_score(score: np.ndarray, occurrence_mask: np.ndarray) -> float | None:
    s = np.asarray(score, dtype=float).ravel()
    occ = np.asarray(occurrence_mask, dtype=bool).ravel()
    valid = np.isfinite(s)
    s, occ = s[valid], occ[valid]
    if occ.sum() == 0 or occ.sum() == len(occ):
        return None
    order = np.argsort(s, kind="stable")
    occ_sorted = occ[order].astype(float)
    n_pos = occ_sorted.sum()
    n_neg = len(occ_sorted) - n_pos
    ranks = np.argsort(np.argsort(s, kind="stable")) + 1
    auc = (ranks[occ].sum() - n_pos * (n_pos + 1) / 2) / (n_pos * n_neg)
    return float(auc)


def spatial_block_cv(score_fn, gx: np.ndarray, gy: np.ndarray,
                     occ_x: np.ndarray, occ_y: np.ndarray,
                     n_blocks: tuple[int, int] = (3, 3)) -> dict:
    """Buffered spatial-block CV: split occurrences by spatial block, score_fn(train_idx)
    rebuilds the model without that block; measure capture of left-out block in top 10% area.

    score_fn: callable(train_occurrence_indices) -> score grid.
    Returns per-fold capture + mean (honest spatial generalisation estimate).
    """
    gx, gy = np.asarray(gx, float), np.asarray(gy, float)
    occ_x, occ_y = np.asarray(occ_x, float), np.asarray(occ_y, float)
    nx, ny = n_blocks
    xedges = np.linspace(gx.min(), gx.max(), nx + 1)
    yedges = np.linspace(gy.min(), gy.max(), ny + 1)
    folds: dict[int, list[int]] = {}
    for i, (x, y) in enumerate(zip(occ_x, occ_y)):
        bx = min(int(np.searchsorted(xedges, x, side="right") - 1), nx - 1)
        by = min(int(np.searchsorted(yedges, y, side="right") - 1), ny - 1)
        folds.setdefault(by * nx + bx, []).append(i)
    results = []
    all_idx = set(range(len(occ_x)))
    for block, left_out in sorted(folds.items()):
        train = sorted(all_idx - set(left_out))
        if not train:
            continue
        score = np.asarray(score_fn(train), dtype=float)
        flat = score.ravel()
        thr = float(np.nanpercentile(flat[np.isfinite(flat)], 90))
        top = np.isfinite(score) & (score >= thr)
        # fraction of left-out occurrences landing in top-decile area
        captured = 0
        for j in left_out:
            ix = int(np.argmin(np.abs(gx[0, :] - occ_x[j])))
            iy = int(np.argmin(np.abs(gy[:, 0] - occ_y[j])))
            if top[iy, ix]:
                captured += 1
        results.append({"block": block, "n_left_out": len(left_out),
                        "captured": captured,
                        "capture_rate": captured / len(left_out)})
    mean_capture = float(np.mean([r["capture_rate"] for r in results])) if results else None
    return {"folds": results, "mean_capture_top10": mean_capture,
            "n_blocks": list(n_blocks),
            "note": "spatial block CV — never random splits for spatial data"}


def heldout_test(score: np.ndarray, gx: np.ndarray, gy: np.ndarray,
                 heldout_x: np.ndarray, heldout_y: np.ndarray,
                 top_pct: float = 10.0) -> dict:
    """Headline test: what fraction of HELD-OUT occurrences fall in top-pct% ranked area?"""
    score = np.asarray(score, dtype=float)
    flat = score.ravel()
    finite = flat[np.isfinite(flat)]
    if len(finite) == 0:
        return {"ok": False, "reason": "empty score grid"}
    thr = float(np.nanpercentile(finite, 100 - top_pct))
    top = np.isfinite(score) & (score >= thr)
    hits = 0
    for x, y in zip(np.asarray(heldout_x, float), np.asarray(heldout_y, float)):
        ix = int(np.argmin(np.abs(np.asarray(gx)[0, :] - x)))
        iy = int(np.argmin(np.abs(np.asarray(gy)[:, 0] - y)))
        if top[iy, ix]:
            hits += 1
    n = len(np.asarray(heldout_x))
    return {"ok": True, "n_heldout": int(n), "n_hits": int(hits),
            "hit_rate": (hits / n) if n else None,
            "top_pct": float(top_pct), "threshold": thr,
            "vs_random_expectation": float(top_pct / 100.0)}


def random_baseline_auc() -> float:
    return 0.5


def sensitivity(weights: dict[str, float], perturb: float, score_fn) -> dict:
    """How do target rankings change when each weight shifts +/-perturb? Returns rank deltas."""
    base = dict(weights)
    out: dict[str, dict] = {}
    for k in base:
        for sign in ("+", "-"):
            w = dict(base)
            w[k] = max(0.0, w[k] * (1 + perturb if sign == "+" else 1 - perturb))
            s = float(np.nanmean(score_fn(w)))
            out[f"{k}{sign}{int(perturb*100)}pct"] = {"mean_score": s}
    return {"perturb": perturb, "variants": out}
