from __future__ import annotations
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from ..database import get_db
from .. import models
from ..deps import current_user

router = APIRouter(tags=["validation"])


@router.get("/runs/{rid}/validation")
async def get_validation(rid: str, user: models.User = Depends(current_user),
                         db: AsyncSession = Depends(get_db)):
    r = await db.get(models.AnalysisRun, rid)
    if r is None:
        raise HTTPException(404, "Run not found")
    p = await db.get(models.Project, r.project_id)
    if p is None or p.org_id != user.org_id:
        raise HTTPException(404, "Run not found")
    res = await db.execute(select(models.ValidationResult).where(models.ValidationResult.run_id == rid))
    vr = res.scalars().first()
    m = r.metrics or {}
    out = {"run_id": rid, "method": r.method, "status": r.status,
           "success_rate": m.get("success_rate", {"ok": False, "reason": "not computed"}),
           "prediction_rate": m.get("prediction_rate", {"ok": False, "reason": "not computed"}),
           "auc_train": m.get("auc_train"),
           "random_baseline_auc": 0.5,
           "heldout": m.get("heldout", {"ok": False}),
           "heldout_names": m.get("heldout_names", []),
           "note": "Unlabelled ground is never treated as barren. Spatial splits only."}
    if vr is not None:
        out["validation_id"] = vr.id
    # label sufficiency statement (honest gating)
    n_train = len(m.get("train_names", []))
    out["label_sufficiency"] = {
        "n_training_occurrences": n_train,
        "wofe_ml_enabled": n_train >= 10,
        "message": ("Sufficient labels for WofE/ML comparison." if n_train >= 10
                    else f"Only {n_train} training occurrences — WofE/ML disabled. "
                           f"Knowledge-driven (weighted/fuzzy) model active.")} if m else {}
    return out


@router.get("/runs/{rid}/compare")
async def compare_runs(ids: str, user: models.User = Depends(current_user),
                       db: AsyncSession = Depends(get_db)):
    """Side-by-side comparison of runs (?ids=a,b) for the swipe-compare tool."""
    out = []
    for rid in ids.split(","):
        rid = rid.strip()
        if not rid:
            continue
        r = await db.get(models.AnalysisRun, rid)
        if r is None:
            continue
        p = await db.get(models.Project, r.project_id)
        if p is None or p.org_id != user.org_id:
            continue
        m = r.metrics or {}
        out.append({"id": r.id, "method": r.method, "status": r.status,
                    "auc_train": m.get("auc_train"),
                    "heldout": m.get("heldout", {}),
                    "score_mean": (m.get("score_stats") or {}).get("mean"),
                    "n_targets": (r.grid_meta or {}).get("n_targets")})
    if not out:
        raise HTTPException(404, "No visible runs")
    return {"runs": out}
