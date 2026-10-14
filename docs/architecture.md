# Architecture

## Runtime (this host: no Docker, no PostGIS, no Redis)
- **API**: FastAPI + SQLAlchemy 2 async, **SQLite** (`storage/mwamba.db`). Geometries are
  GeoJSON text + centroid lon/lat columns. All persistence goes through
  `apps/api/app/database.py` + `models.py`, so a PostGIS backend replaces the engine
  without touching routers/services.
- **Engine**: `packages/geo/mwamba_geo` — pure Python, no FastAPI imports, installed
  editable (`pip install -e packages/geo`). CRS, validation, features, scoring, metrics.
- **Jobs**: `POST /runs` enqueues via `worker.launch_run()`. With `REDIS_URL` set it
  dispatches to Celery (`workers/celery_app.py`); otherwise FastAPI `BackgroundTasks`
  runs the **same** `run_analysis_sync()` in-process. Progress is on the run row
  (`queued → running → done/failed`, `progress` 0..1) and polled by the UI.
- **Grids**: NumPy `.npy`/`.npz` in `storage/grids`. Served to the map as sampled
  GeoJSON points (`/runs/{id}/grid_points`) and PNG data-URL (`/runs/{id}/grid_png`) —
  no TiTiler required. TiTiler/MinIO path is documented in `infra/` for Docker hosts.
- **Frontend**: React + Vite + TS, MapLibre GL JS over free OSM raster tiles,
  TanStack Query (server state), Zustand (UI state, URL-shared map view), Recharts.

## Request flow (analysis)
`POST /runs` → row (`queued`) → background `run_analysis_sync`:
1. Load project AOI → `mwamba_geo.grid.build_grid` (UTM 36S, default 100 m pilot,
   hard cap `MWAMBA_MAX_GRID_CELLS`).
2. Evidence layers from datasets: `dist_structure` (exponential decay on distance to
   faults/shears), `fault_density` (Gaussian kernel), `lithology` (per-unit scores),
   `geochem_au` (log-IDW + percentile normalisation). Absent data → NaN, never zero.
3. Label gate: `wofe`/`logreg` need ≥10 occurrences or fail fast with a plain message.
4. Scoring: weighted overlay (NaN-aware) or fuzzy gamma. Coverage layer alongside.
5. Deterministic holdout split (sorted names, last N) → success/prediction curves,
   AUC, held-out hit rate. Targets: percentile threshold → connected regions →
   min-area filter → rank by (mean, coverage, area). Constraints intersected per target.
6. Persist grids + targets + metrics + validation row. Same inputs + seed ⇒
   byte-identical grid (tested in `apps/api/tests/test_api.py`).

## Data model
See `CLAUDE.md` (condensed ERD). Provenance on every dataset (`provenance`,
`processing_history`, `quality`, `status_label`). Audit log on imports, runs,
reviews, exports. Org-scoped queries everywhere; roles admin/geologist/analyst/viewer.
