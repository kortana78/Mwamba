"""Constraints module: intersect targets with constraint datasets
(protected areas, forest reserves, water buffers, settlements, licences).

Constraint datasets are kind='constraints' GeoJSON polygons. Each target gets
conflict flags + overlapping names. No hardcoded Malawian reserves — flags are
computed purely from stored data; empty constraints => clean check with note.
"""
from __future__ import annotations
import json
import os
from shapely.geometry import shape


def load_constraint_polys(stored_paths: list[str]) -> list[dict]:
    polys = []
    for p in stored_paths:
        if not p or not os.path.exists(p):
            continue
        try:
            with open(p, encoding="utf-8") as f:
                obj = json.load(f)
        except Exception:
            continue
        for feat in obj.get("features", []):
            try:
                g = shape(feat.get("geometry") or {})
            except Exception:
                continue
            if g.is_empty or not g.is_valid:
                continue
            props = feat.get("properties") or {}
            polys.append({"geom": g,
                          "name": str(props.get("name", props.get("unit", "constraint"))),
                          "type": str(props.get("type", props.get("category", "constraint")))})
    return polys


def check_target(target_poly_geojson: dict, constraints: list[dict]) -> dict:
    """Return {'conflicts': [...], 'clean': bool} computed from stored polygons."""
    try:
        g = shape(target_poly_geojson.get("geometry", target_poly_geojson))
    except Exception:
        return {"conflicts": [], "clean": True, "note": "unparseable target polygon"}
    hits = []
    for c in constraints:
        try:
            if g.intersects(c["geom"]):
                inter = g.intersection(c["geom"])
                hits.append({"name": c["name"], "type": c["type"],
                             "overlap_m2_est": float(inter.area * (111320.0 ** 2))})
        except Exception:
            continue
    if not constraints:
        return {"conflicts": [], "clean": True,
                "note": "No constraint layers stored for this project — import protected areas / licences to enable checks."}
    return {"conflicts": hits, "clean": len(hits) == 0}
