"""Evidence groups: which layers satisfy which geological requirements.

Every evidence layer key maps to one or more evidence groups. Each commodity
template declares required groups. A run is "sufficient" only when every
required group has at least one finite evidence layer.
"""
from __future__ import annotations

CODE_VERSION = "0.1.0"

#: layer key -> evidence groups it satisfies
LAYER_GROUPS: dict[str, list[str]] = {
    # structure group (gold + REE share this)
    "dist_structure": ["structure"],
    "fault_density": ["structure"],
    "lineament_density": ["structure"],
    "lineament_intersection": ["structure"],
    "drainage_density": ["structure"],
    # gold host / trap
    "lithology": ["host_lithology", "radiometric_or_alkaline_lithology"],
    "alkaline_lithology": ["radiometric_or_alkaline_lithology", "host_lithology"],
    # gold alteration / direct detection
    "geochem_au": ["alteration_or_geochem"],
    "geochem_ree": ["radiometric_or_alkaline_lithology", "alteration_or_geochem"],
    "alteration_iron_oxide": ["alteration_or_geochem"],
    "alteration_clay": ["alteration_or_geochem"],
    "alteration_mask": ["alteration_or_geochem"],
    # REE extras
    "radiometric_total": ["radiometric_or_alkaline_lithology"],
    "radiometric_th_k": ["radiometric_or_alkaline_lithology"],
    "magnetics": ["magnetic_optional"],
    # preservation proxy: computed everywhere a DEM exists, but never counts
    # toward sufficiency on its own (a smooth slope surface is not targeting).
    "dem_slope": [],
}

#: commodity -> required evidence groups (optional groups listed separately)
COMMODITY_REQUIREMENTS: dict[str, dict[str, list[str]]] = {
    "Au": {
        "required": ["structure", "host_lithology", "alteration_or_geochem"],
        "optional": [],
    },
    "REE": {
        "required": ["radiometric_or_alkaline_lithology", "structure"],
        "optional": ["magnetic_optional", "alteration_or_geochem"],
    },
    "C": {
        "required": ["radiometric_or_alkaline_lithology", "structure"],
        "optional": ["magnetic_optional"],
    },
    "Nb": {
        "required": ["radiometric_or_alkaline_lithology", "structure"],
        "optional": ["magnetic_optional", "alteration_or_geochem"],
    },
    "Ti": {
        "required": ["host_lithology", "structure"],
        "optional": ["alteration_or_geochem"],
    },
    "U": {
        "required": ["structure", "host_lithology", "alteration_or_geochem"],
        "optional": [],
    },
}

INSUFFICIENT_LABEL = "INSUFFICIENT EVIDENCE — not a targeting result"


def groups_for_layers(layer_keys: list[str]) -> dict[str, list[str]]:
    """Map present layer keys -> group -> contributing layer keys."""
    out: dict[str, list[str]] = {}
    for key in layer_keys:
        for grp in LAYER_GROUPS.get(key, []):
            out.setdefault(grp, []).append(key)
    return out


def evaluate_evidence(commodity: str, layer_keys: list[str],
                      required_override: list[str] | None = None) -> dict:
    """Evaluate sufficiency for a commodity given present layer keys."""
    req = COMMODITY_REQUIREMENTS.get(commodity, COMMODITY_REQUIREMENTS["Au"])
    required = list(required_override) if required_override is not None else list(req["required"])
    present = groups_for_layers(layer_keys)
    missing = [g for g in required if g not in present]
    return {
        "commodity": commodity,
        "required_groups": required,
        "optional_groups": list(req.get("optional", [])),
        "present_groups": {g: sorted(v) for g, v in sorted(present.items())},
        "missing_groups": missing,
        "sufficient": len(missing) == 0,
        "note": (None if not missing else
                 f"{INSUFFICIENT_LABEL}: missing groups {missing}. "
                 f"Surface is for inspection only — no ranked targets generated."),
    }
