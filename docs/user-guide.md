# User guide

1. **Sign in** (`admin@mwamba.local / Mwamba123!` on a fresh install; change it).
2. **Workspace**: pick the demo project or create one (commodity + AOI polygon + grid).
3. **Ingest**: upload GeoJSON/CSV (declare CRS — never guessed) or a PDF report.
   Read the quality report; fix errors; confirm. Check provenance badges in Data Library.
4. **Map**: toggle evidence layers, pick a run, click features for the inspector.
   Cursor readout is DD; dossier shows UTM 36S too. URL shares the view.
5. **Models**: set weights, launch a run, watch progress on the map panel.
6. **Targets**: ranked table → dossier (score breakdown, missing evidence,
   constraints, next steps, PDF). Geologist review flips MODEL OUTPUT → REVIEWED.
7. **Validation**: success vs prediction-rate curves, held-out hit rate vs the 10%
   random baseline, label-sufficiency statement for WofE/ML.
8. **Reports**: export GeoJSON/CSV/KML/PDF; compare two runs side by side.
9. **Admin**: users, audit log, API keys (`Authorization: Bearer mw_…`), report
   review queue, source registry verification.

Badges everywhere: VERIFIED (sourced) · DERIVED (computed) · SYNTHETIC (fixture) ·
MODEL OUTPUT (unvalidated) · REVIEWED (signed off).
