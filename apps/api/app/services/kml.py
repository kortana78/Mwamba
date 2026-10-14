"""Minimal KML reader (stdlib only): first Polygon / MultiGeometry / Placemark
with an outer boundary -> GeoJSON Polygon. No new dependencies."""
from __future__ import annotations
import xml.etree.ElementTree as ET


def _local(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def _parse_coords(text: str) -> list[list[float]]:
    pts = []
    for tup in (text or "").strip().split():
        parts = tup.split(",")
        if len(parts) < 2:
            continue
        try:
            pts.append([float(parts[0]), float(parts[1])])
        except ValueError:
            continue
    return pts


def kml_to_aoi(raw: bytes) -> dict:
    """Return a GeoJSON Polygon from KML bytes. Raises ValueError when none found."""
    try:
        root = ET.fromstring(raw)
    except Exception as e:
        raise ValueError(f"Invalid KML/XML: {e}")
    for el in root.iter():
        if _local(el.tag) != "Polygon":
            continue
        outer = None
        for sub in el.iter():
            if _local(sub.tag) == "outerBoundaryIs":
                outer = sub
                break
        if outer is None:
            continue
        for sub in outer.iter():
            if _local(sub.tag) == "coordinates" and sub.text:
                ring = _parse_coords(sub.text)
                if len(ring) >= 4:
                    if ring[0] != ring[-1]:
                        ring.append(ring[0])
                    return {"type": "Polygon", "coordinates": [ring]}
    raise ValueError("No Polygon with outer boundary found in this KML")
