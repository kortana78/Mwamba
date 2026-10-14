"""Exports: GeoJSON / CSV / KML / PDF dossier. Everything computed from stored rows."""
from __future__ import annotations
import csv
import io
import json


def targets_geojson(targets: list) -> dict:
    feats = []
    for t in targets:
        poly = dict(t.polygon_geojson or {})
        props = {"id": t.id, "rank": t.rank, "area_m2": t.area_m2,
                 "centroid_lon": t.centroid_lon, "centroid_lat": t.centroid_lat,
                 "mean_score": t.mean_score, "max_score": t.max_score,
                 "coverage": t.coverage, "status_label": t.status_label,
                 "review_status": t.review_status}
        if poly.get("type") == "Feature":
            poly["properties"] = {**(poly.get("properties") or {}), **props}
            feats.append(poly)
        else:
            feats.append({"type": "Feature",
                          "geometry": poly.get("geometry", poly),
                          "properties": props})
    return {"type": "FeatureCollection", "features": feats,
            "properties": {"note": "MODEL OUTPUT — relative rankings, not deposit probabilities"}}


def targets_csv(targets: list) -> str:
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(["id", "rank", "area_m2", "centroid_lon", "centroid_lat",
                "centroid_easting", "centroid_northing",
                "mean_score", "max_score", "coverage", "status_label", "review_status"])
    for t in targets:
        w.writerow([t.id, t.rank, round(t.area_m2, 1), round(t.centroid_lon, 6),
                    round(t.centroid_lat, 6), round(t.centroid_easting, 1),
                    round(t.centroid_northing, 1), round(t.mean_score, 4),
                    round(t.max_score, 4), round(t.coverage, 4),
                    t.status_label, t.review_status])
    return buf.getvalue()


def targets_kml(targets: list, project_name: str = "Mwamba") -> str:
    parts = ['<?xml version="1.0" encoding="UTF-8"?>',
             '<kml xmlns="http://www.opengis.net/kml/2.2"><Document>',
             f"<name>{project_name} targets (MODEL OUTPUT)</name>"]
    for t in targets:
        poly = t.polygon_geojson or {}
        geom = poly.get("geometry", poly)
        coords = ""
        if geom.get("type") == "Polygon":
            coords = " ".join(f"{x},{y},0" for x, y in geom["coordinates"][0])
        parts.append(f"<Placemark><name>Target {t.rank}</name>"
                     f"<description>mean {t.mean_score:.3f} max {t.max_score:.3f} "
                     f"coverage {t.coverage:.0%} area {t.area_m2:,.0f} m2</description>"
                     f"<Polygon><outerBoundaryIs><LinearRing><coordinates>{coords}"
                     f"</coordinates></LinearRing></outerBoundaryIs></Polygon></Placemark>")
    parts.append("</Document></kml>")
    return "\n".join(parts)


def dossier_pdf_bytes(target, run, project) -> bytes:
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.units import mm
    from reportlab.pdfgen import canvas
    buf = io.BytesIO()
    c = canvas.Canvas(buf, pagesize=A4)
    w, h = A4
    y = h - 20 * mm
    c.setFont("Helvetica-Bold", 16)
    c.drawString(20 * mm, y, f"Target {target.rank} dossier — {project.commodity} (MODEL OUTPUT)")
    y -= 8 * mm
    c.setFont("Helvetica", 9)
    lines = [
        f"Target ID: {target.id}   Run: {run.id} ({run.method})   Code v{run.code_version}",
        f"Centroid: {target.centroid_lat:.5f}, {target.centroid_lon:.5f} (DD)  |  "
        f"E {target.centroid_easting:,.0f}  N {target.centroid_northing:,.0f} (UTM 36S)",
        f"Area: {target.area_m2:,.0f} m2   Mean score: {target.mean_score:.3f}   "
        f"Max: {target.max_score:.3f}   Coverage: {target.coverage:.0%}",
        f"Status: {target.status_label}   Review: {target.review_status}",
        "",
        "Scores are relative rankings (0..1), NOT probability of an economic deposit.",
    ]
    for ln in lines:
        c.drawString(20 * mm, y, ln[:115])
        y -= 5 * mm
    ev = target.evidence or {}
    y -= 3 * mm
    c.setFont("Helvetica-Bold", 11)
    c.drawString(20 * mm, y, "Score breakdown per evidence layer")
    y -= 6 * mm
    c.setFont("Helvetica", 9)
    for k, v in (ev.get("per_layer") or {}).items():
        bar = "" if v is None else "#" * int(round(v * 30))
        c.drawString(20 * mm, y, f"{k:20s} {'missing' if v is None else f'{v:.3f} {bar}'}")
        y -= 5 * mm
    y -= 2 * mm
    c.setFont("Helvetica-Bold", 11)
    c.drawString(20 * mm, y, "Supporting / conflicting / missing")
    y -= 6 * mm
    c.setFont("Helvetica", 9)
    for key in ("supporting", "conflicting", "missing_evidence"):
        c.drawString(20 * mm, y, f"{key}: {', '.join(ev.get(key) or []) or '—'}")
        y -= 5 * mm
    cons = ev.get("constraints") or {}
    y -= 2 * mm
    c.setFont("Helvetica-Bold", 11)
    c.drawString(20 * mm, y, "Constraints check")
    y -= 6 * mm
    c.setFont("Helvetica", 9)
    if cons.get("clean"):
        c.drawString(20 * mm, y, "Clean — " + str(cons.get("note", "no overlaps with stored constraint layers.")))
        y -= 5 * mm
    else:
        for cf in cons.get("conflicts", []):
            c.drawString(20 * mm, y, f"CONFLICT: {cf.get('type')} — {cf.get('name')}")
            y -= 5 * mm
    y -= 2 * mm
    c.setFont("Helvetica-Bold", 11)
    c.drawString(20 * mm, y, "Recommended next steps (rules-based)")
    y -= 6 * mm
    c.setFont("Helvetica", 9)
    for s in ev.get("next_steps", []):
        c.drawString(22 * mm, y, "• " + s[:110])
        y -= 5 * mm
        if y < 25 * mm:
            c.showPage()
            y = h - 20 * mm
    metrics = run.metrics or {}
    gate = metrics.get("evidence_gate")
    if gate:
        y -= 2 * mm
        c.setFont("Helvetica-Bold", 11)
        c.drawString(20 * mm, y, "Evidence gate")
        y -= 6 * mm
        c.setFont("Helvetica", 9)
        c.drawString(20 * mm, y, f"sufficient: {gate.get('sufficient')}  "
                     f"missing: {', '.join(gate.get('missing_groups') or []) or '—'}"[:115])
        y -= 5 * mm
    cits = metrics.get("occurrence_citations") or {}
    if cits:
        y -= 2 * mm
        c.setFont("Helvetica-Bold", 11)
        c.drawString(20 * mm, y, "Occurrence citations")
        y -= 6 * mm
        c.setFont("Helvetica", 9)
        for nm, cit in list(cits.items())[:12]:
            c.drawString(22 * mm, y, f"• {nm}: {cit}"[:112])
            y -= 5 * mm
            if y < 25 * mm:
                c.showPage()
                y = h - 20 * mm
    c.showPage()
    c.save()
    return buf.getvalue()


def project_summary(project, datasets: list, runs: list, targets: list) -> dict:
    visible = [d for d in datasets if not ((d.provenance or {}).get("restricted"))]
    n_restricted = len(datasets) - len(visible)
    return {
        "project": {"id": project.id, "name": project.name, "commodity": project.commodity,
                    "grid_m": project.grid_m, "status_label": project.status_label},
        "counts": {"datasets": len(visible), "runs": len(runs), "targets": len(targets),
                   "restricted_excluded": n_restricted},
        "datasets": [{"id": d.id, "name": d.name, "kind": d.kind, "status_label": d.status_label,
                      "feature_count": d.feature_count} for d in visible],
        "latest_run": ({"id": runs[-1].id, "method": runs[-1].method, "status": runs[-1].status,
                        "metrics": runs[-1].metrics} if runs else None),
        "note": ("All metrics computed from stored data. Empty states shown when absent."
                 + (f" {n_restricted} restricted dataset(s) excluded from this export (local-only licence)."
                    if n_restricted else "")),
    }
