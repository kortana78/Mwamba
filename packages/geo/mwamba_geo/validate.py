"""Validation of uploaded GeoJSON / CSV: geometry, Malawi bounds, duplicates,
impossible values, unit consistency, detection-limit strings (e.g. '<0.01').

All functions are pure and return a quality-report dict that the API stores
verbatim on the dataset. Nothing is auto-fixed silently.
"""
from __future__ import annotations
import csv
import io
import json
import math
from typing import Any

from shapely.geometry import shape
from .crs import MALAWI_BBOX, in_malawi

VALID_STATUS = {"VERIFIED", "DERIVED", "SYNTHETIC", "MODEL OUTPUT", "REVIEWED"}
VALID_KINDS = {"geology", "structure", "geophysics", "geochem", "remotesensing",
               "occurrences", "constraints", "dem", "report"}


def parse_detection_limit(value: Any) -> dict:
    """Parse geochem values incl. below-detection-limit strings like '<0.01'.

    Returns {'value': float|None, 'censored': bool, 'raw': str}.
    """
    if value is None or (isinstance(value, str) and value.strip() in ("", "NA", "n/a", "-")):
        return {"value": None, "censored": False, "raw": str(value)}
    if isinstance(value, (int, float)):
        v = float(value)
        return {"value": v, "censored": False, "raw": str(value)}
    s = str(value).strip()
    if s.startswith("<"):
        try:
            v = float(s[1:].strip())
            return {"value": v / 2.0, "censored": True, "raw": s,
                    "note": "below detection limit; substituted with DL/2 and flagged"}
        except ValueError:
            return {"value": None, "censored": False, "raw": s, "error": "unparseable DL string"}
    try:
        return {"value": float(s.replace(",", "")), "censored": False, "raw": s}
    except ValueError:
        return {"value": None, "censored": False, "raw": s, "error": "unparseable number"}


def validate_geojson(obj: dict, *, kind: str = "occurrences",
                     value_field: str | None = None) -> dict:
    """Validate a GeoJSON FeatureCollection. Returns a quality report dict."""
    errors: list[str] = []
    warnings: list[str] = []
    if not isinstance(obj, dict) or obj.get("type") != "FeatureCollection":
        return {"ok": False, "errors": ["Root must be a GeoJSON FeatureCollection"], "warnings": []}
    features = obj.get("features", [])
    if not isinstance(features, list):
        return {"ok": False, "errors": ["'features' must be a list"], "warnings": []}
    n_total = len(features)
    n_valid = 0
    n_out_of_malawi = 0
    n_invalid_geom = 0
    seen: dict[tuple, int] = {}
    n_duplicates = 0
    impossible: list[str] = []
    censored_count = 0

    for i, f in enumerate(features):
        try:
            geom = shape(f.get("geometry") or {})
        except Exception:
            n_invalid_geom += 1
            errors.append(f"feature {i}: unparseable geometry")
            continue
        if geom.is_empty:
            n_invalid_geom += 1
            errors.append(f"feature {i}: empty geometry")
            continue
        if not geom.is_valid:
            n_invalid_geom += 1
            warnings.append(f"feature {i}: invalid geometry ({geom.is_valid_reason if hasattr(geom, 'is_valid_reason') else 'self-intersection'})")
            continue
        n_valid += 1
        rep = geom.representative_point() if geom.geom_type != "Point" else geom
        lon, lat = float(rep.x), float(rep.y)
        # Heuristic: coordinates that look like metres (UTM) rather than degrees
        if abs(lon) > 180 or abs(lat) > 90:
            errors.append(f"feature {i}: coordinates ({lon:.1f},{lat:.1f}) out of degree range — "
                          f"CRS may be projected (e.g. EPSG:20936/32736). Declare CRS explicitly; never guessed.")
            continue
        if not in_malawi(lon, lat):
            n_out_of_malawi += 1
        key = (round(lon, 6), round(lat, 6), geom.geom_type)
        if key in seen:
            n_duplicates += 1
        else:
            seen[key] = i
        props = f.get("properties") or {}
        if value_field and value_field in props:
            parsed = parse_detection_limit(props[value_field])
            if parsed.get("censored"):
                censored_count += 1
            if parsed.get("value") is not None and parsed["value"] < 0:
                impossible.append(f"feature {i}: negative {value_field}={props[value_field]}")
    if n_out_of_malawi:
        warnings.append(f"{n_out_of_malawi}/{n_total} features fall outside Malawi bbox {MALAWI_BBOX}")
    if n_duplicates:
        warnings.append(f"{n_duplicates} possible duplicate locations (rounded to 6dp)")
    if impossible:
        errors.extend(impossible)
    if kind not in VALID_KINDS:
        warnings.append(f"unknown kind '{kind}'; expected one of {sorted(VALID_KINDS)}")
    return {
        "ok": len(errors) == 0,
        "errors": errors,
        "warnings": warnings,
        "stats": {
            "n_total": n_total, "n_valid": n_valid,
            "n_invalid_geom": n_invalid_geom,
            "n_out_of_malawi": n_out_of_malawi,
            "n_duplicates": n_duplicates,
            "n_censored_dl": censored_count,
        },
    }


def validate_csv(text: str, *, lon_field: str = "lon", lat_field: str = "lat",
                 value_field: str | None = "Au_ppb") -> dict:
    """Validate a CSV/XLSX-as-text upload with coordinate columns."""
    errors: list[str] = []
    warnings: list[str] = []
    try:
        reader = csv.DictReader(io.StringIO(text))
        if reader.fieldnames is None:
            return {"ok": False, "errors": ["empty CSV"], "warnings": []}
        rows = list(reader)
    except Exception as e:
        return {"ok": False, "errors": [f"CSV parse error: {e}"], "warnings": []}
    if lon_field not in (reader.fieldnames or []) or lat_field not in (reader.fieldnames or []):
        return {"ok": False,
                "errors": [f"coordinate columns '{lon_field}'/'{lat_field}' not found. Found: {reader.fieldnames}. Map columns explicitly."],
                "warnings": []}
    n_total = len(rows)
    n_out = 0
    n_bad = 0
    n_censored = 0
    seen: set = set()
    n_dup = 0
    for i, r in enumerate(rows):
        try:
            lon = float(str(r[lon_field]).strip())
            lat = float(str(r[lat_field]).strip())
        except (ValueError, TypeError):
            n_bad += 1
            errors.append(f"row {i + 2}: bad coordinates lon={r.get(lon_field)!r} lat={r.get(lat_field)!r}")
            continue
        if not (math.isfinite(lon) and math.isfinite(lat)):
            n_bad += 1
            errors.append(f"row {i + 2}: non-finite coordinates")
            continue
        if abs(lon) > 180 or abs(lat) > 90:
            n_bad += 1
            errors.append(f"row {i + 2}: coordinates out of degree range — declare CRS (maybe UTM metres)")
            continue
        if not in_malawi(lon, lat):
            n_out += 1
        key = (round(lon, 6), round(lat, 6))
        if key in seen:
            n_dup += 1
        seen.add(key)
        if value_field and value_field in r:
            p = parse_detection_limit(r[value_field])
            if p.get("censored"):
                n_censored += 1
            if p.get("value") is not None and p["value"] < 0:
                errors.append(f"row {i + 2}: negative {value_field}")
    if n_out:
        warnings.append(f"{n_out}/{n_total} rows outside Malawi bbox")
    if n_dup:
        warnings.append(f"{n_dup} duplicate coordinate pairs")
    if n_censored:
        warnings.append(f"{n_censored} below-detection-limit values (substituted DL/2, flagged)")
    return {"ok": len(errors) == 0, "errors": errors, "warnings": warnings,
            "stats": {"n_total": n_total, "n_bad_coords": n_bad,
                      "n_out_of_malawi": n_out, "n_duplicates": n_dup,
                      "n_censored_dl": n_censored}}
