# 5-minute demo script (UniPod evaluators)

Seeded on first boot: admin `admin@mwamba.local / Mwamba123!` (env overrides in
production), analyst demo account for one-click "Try the demo",
**Chitipa Gold — Synthetic demo (SYNTHETIC)** with 4 fixture datasets, plus
**Chitipa Gold — Real data (evidence incomplete)** (Copernicus DEM + USGS sweep)
and a Chilwa REE pilot with no pre-loaded coordinates.

1. (0:00) **Question**: "Where next for gold in Chitipa, why, how confident, what's
   missing?" Sign in; Workspace shows the pilot project (SYNTHETIC badge).
2. (0:45) **Data honesty**: Data Library → open a quality + provenance report.
   Ingest → Validate-only a bad file (projected coordinates rejected with CRS hint).
3. (1:30) **Map**: toggle structures/geology/geochem overlays; click a fault for the
   inspector (attributes + status badge). Note OSM attribution, viridis ramp.
4. (2:15) **Run**: Models → weighted overlay → Run. Progress bar completes in seconds.
5. (3:00) **Targets**: ranked table → dossier #1: score bars, missing evidence,
   constraints, next steps, PDF download.
6. (3:45) **Headline validation**: Validation page — **held-out 4/4 in top-10% area
   (vs 10% random), AUC ≈ 0.97 on SYNTHETIC ground truth**. Stress: fixtures prove
   the pipeline; real validation needs real GSD/company data.
7. (4:30) **Trust**: re-run → identical grid (determinism test); review workflow
   flips MODEL OUTPUT → REVIEWED; audit log; exports (GeoJSON/CSV/KML).

Close: roadmap — PostGIS/TiTiler on Docker hosts, WofE training, Sentinel-2 auto
pipeline, Playwright E2E in CI.
