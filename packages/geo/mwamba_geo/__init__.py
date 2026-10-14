"""mwamba_geo — shared pure-python exploration engine (no FastAPI imports)."""
from .crs import MALAWI_BBOX, MALAWI_CRS_STORAGE, MALAWI_CRS_ANALYSIS, reproject_point, log_reprojection
from .scoring import weighted_overlay, fuzzy_overlay, coverage_layer
from .validation import success_rate_curve, prediction_rate_curve, spatial_block_cv, auc_score, heldout_test

__all__ = [
    "MALAWI_BBOX", "MALAWI_CRS_STORAGE", "MALAWI_CRS_ANALYSIS",
    "reproject_point", "log_reprojection",
    "weighted_overlay", "fuzzy_overlay", "coverage_layer",
    "success_rate_curve", "prediction_rate_curve", "spatial_block_cv",
    "auc_score", "heldout_test",
]
__version__ = "0.1.0"
