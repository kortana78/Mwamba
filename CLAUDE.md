# MWAMBA — Malawi Mineral Exploration Intelligence Platform
# Living project memory. Update at the end of every milestone.

## Mission
Turn Malawi's scattered geological, geophysical, geochemical, remote-sensing and
historical exploration data into ranked, explainable, field-ready exploration targets.
Core question: "Where should we look next for commodity X, why there, how confident
are we, and what is missing?"

## Status (2026-10-14, sprint: SHIP LIVE PROTOTYPE — GitHub + Render, verified local)

- A. Prototype completion: DONE (verified run 2026-10-14) — evidence gate
  (required groups per commodity, INSUFFICIENT label, 0 targets when gated),
  targets capped 1–20 (p95/200k m²/500 m merge/max 20, tested), DEM lineaments +
  drainage density (DERIVED unverified proxy), cited-occurrence form (VERIFIED only
  with author+year+title, else UNVERIFIED), badges VERIFIED/MIXED/EVIDENCE
  INCOMPLETE/SYNTHETIC/No data. Seed: "Chitipa Gold — Synthetic demo
  (SYNTHETIC)" (full loop) + "Chitipa Gold — Real data (evidence incomplete)"
  (DEM+USGS, honestly gated) + Chilwa REE pilot (no invented coords).
  Tests: 35 pytest + 3 vitest GREEN; `tsc` clean; Playwright happy path ships
  (`tests/e2e/happy-path.spec.ts`, excluded from vitest) + `docs/smoke-test.md`.
- B. Repo prep: DONE — structure /apps/api /apps/web /packages/geo /data/fixtures
  /data/real /docs /scripts; .gitignore covers .env/*.db/uploads/__pycache__/
  node_modules/dist/.venv + raw 40 MB tile + WDPA; data/real audit in
  docs/data-sources.md (USGS + manifest pushed; DEM crop 2.5 MB + districts
  5.4 MB + picker 2.5 MB PENDING push — build-machine uplink 408s on MB bodies,
  push from faster network per docs/deploy-render.md §2b; app degrades gracefully;
  nothing >50 MB); secrets scan clean (dev
  defaults only, env overrides in prod); README rewritten (demo placeholder,
  features, labels, Mermaid, Win+Linux setup, deploy, limits, roadmap, licence);
  LICENSE MIT (data under source licences); CI `.github/workflows/ci.yml`
  (backend pytest + frontend test/build). Git/gh NOT available on this host —
  user must `git init`, `gh auth login`, `gh repo create mwamba --private --source=. --push`.
- C. Backend Render: DONE (verified local) — entry `uvicorn
  apps.api.app.main:app`; requirements pinned (rasterio wheels, no GDAL/system
  needed; geopandas intentionally unused); `.python-version` 3.11;
  `/health` + `/api/health` 200; CORS via MWAMBA_CORS_ORIGINS + FRONTEND_ORIGIN;
  env aliases JWT_SECRET/DATABASE_URL/ADMIN_*/DEMO_*/MAX_UPLOAD_MB/FRONTEND_ORIGIN;
  ephemeral SQLite seeded on boot + DEMO banner copy; in-process jobs with
  MWAMBA_MAX_GRID_CELLS + 240 s timeout + clear error; demo account analyst
  (can run, 403 on Admin) + POST /auth/demo + GET /auth/demo-config.
- D. Frontend Render: DONE — `npm ci && npm run build` → `apps/web/dist`;
  VITE_API_URL (scheme-tolerant) + /api dev proxy; SPA rewrite in render.yaml;
  "Try the demo" button (server-minted token, no password on screen);
  cold-start "Waking the server — up to a minute" in api client + login.
- E. render.yaml Blueprint: DONE — mwamba-api (env python 3.11.9, build pip
  requirements + packages/geo, health /api/health, JWT_SECRET generateValue,
  rest sync:false) + mwamba-web (static, rewrite /* → /index.html, VITE_API_URL
  fromService). Guide + verify checklist + limitations in docs/deploy-render.md.
- F. Verify after deploy: NOT DONE live (no git/Render on this host). Local:
  health aliases 200, demo login 200 + analyst + admin 403, seed names/roles
  confirmed, full pytest/vitest/build green. Live URLs pending user deploy;
  record in docs/deploy-render.md log + README.

## Status (2026-10-13, sprint: real data + UX)
- A. UX fixes: DONE (unverified run) — project status derives from datasets
  ("No data"/SYNTHETIC/VERIFIED/MIXED, never VERIFIED when empty); commodity
  dropdown (Au/C/REE/Nb/Ti/U enforced); AOI wizard (draw-rectangle, 28-district
  picker, GeoJSON/KML upload, advanced paste; Malawi validation server-side);
  solid Create button w/ honest disabled state; Targets run selector (defaults to
  latest completed); login lands on last project's Map; demo creds only when
  VITE_DEMO_MODE; branded login panel. Seed has no test projects.
- B. Ingestion: DONE (unverified run) — zipped shapefile (pyshp), GeoPackage
  (stdlib sqlite, 4326-only, layer picker), KML, GeoTIFF/COG (rasterio: CRS/nodata/
  resolution/Malawi-extent; DEM slope stats); CRS auto-detect for Malawi UTM36S
  (32736 vs Arc1950 20936) with logged transform; ambiguous input rejected, user asked.
- C. Real Chitipa data (all verified live 2026-10-13, manifest in data/real/):
  REAL — Copernicus DEM crop (VERIFIED), USGS MRDS sweep (VERIFIED+cited:
  1 stone record in AOI, 1 Nb prospect nearby, ZERO gold occurrences — recorded);
  districts (CC-BY 3.0 IGO). MANUAL-IMPORT — Sentinel-2 (scene ID + query saved,
  needs free PC account), OSM (Overpass overloaded at fetch time, queries saved),
  protected areas (registration). SYNTHETIC stays in the demo project only.
- D. Real-data run: EXECUTED live 2026-10-13 (`scripts/run_real_demo.py`).
  Real project (status VERIFIED): Copernicus DEM + USGS sweep. Weighted AND fuzzy
  both completed using only `dem_slope` (single real layer): score mean 0.637,
  coverage 1.00, 197 targets (p90/min-area — fragmented, as expected from one
  smooth proxy layer). Validation honestly empty: 0 train/0 held-out (both USGS
  records correctly excluded by commodity filter: stone + Nb ≠ Au, skipped=2
  counted), AUC None, WofE/ML disabled message shown. Fuzzy == weighted is
  mathematically expected with a single input layer.
- E. Platform: DEMO_MODE enforced server-side (viewers read-only; demo@mwamba.local
  seeded when on); render.yaml + Dockerfile.api; docs/postgis-migration.md plan.
- Engine additions: dem_slope evidence layer (low-slope preservation proxy);
  occurrence commodity filter (non-matching records excluded + counted).
- Frontend: DEM hillshade image overlay on map; models expose dem_slope weight.
- Tests: 25 pytest + 2 vitest GREEN (verified run 2026-10-13); tsc clean.
  New tests cover parse-aoi/KML/shp/gpkg/tiff-rejects/hillshade-gate/status-derive/
  UTM36S-auto-detect/project-validation.
- Still missing: OSM + S2 + protected-areas layers (blocked as above), WofE
  training, Playwright E2E, PostGIS cutover (plan only).

## Environment adaptation (IMPORTANT)
The brief asks for Docker Compose + PostGIS + TiTiler + Redis/Celery. This build
machine has **no Docker, no git, no PostGIS, no Redis**. Decision:
- DB: SQLite (aiosqlite) + SQLAlchemy 2 async. Geometries stored as GeoJSON text
  with centroid lat/lon columns. Repository layer is isolated in `apps/api/app/database.py`
  and `models.py` so a PostGIS backend can replace it without touching routers/services.
- Jobs: FastAPI `BackgroundTasks` + `jobs` table (progress 0..1). `workers/` Celery app
  is written and activates automatically when `REDIS_URL` is set; otherwise the API
  runs jobs in-process. Same function signature both paths (see `apps/api/app/worker.py`).
- Raster tiles: TiTiler/MinIO path documented in `infra/` but NOT required to run.
  The API serves prospectivity grids as sampled GeoJSON points + PNG data-URL so the
  map works with zero raster infrastructure.
- Frontend map uses free OSM raster tiles (no key) + MapLibre GL JS.
- `infra/docker-compose.yml` is still shipped for reviewers with Docker, but
  `README.md` documents the one-command local run without Docker:
  `pip install -r requirements.txt` then `uvicorn` + `npm run dev`.

## Architecture
```
apps/api/app/          FastAPI backend (routers/, services/, worker.py)
  routers: auth, projects, datasets, ingest, runs, targets, validation, reports, admin, sources
  services: ingest_validate, prospectivity, targets, validation_metrics, exports, constraints
packages/geo/          Pure-python shared lib (no FastAPI imports): mwamba_geo/
  crs.py               EPSG:4326 <-> EPSG:32736 <-> EPSG:20936 (Arc1950/UTM36S) transforms, logging
  validate.py          GeoJSON/CSV validation: geometry, Malawi bounds, duplicates, values, DL strings
  features.py          distance-to-structure decay, fault density, lithology scores, IDW geochem, slope proxy
  scoring.py           weighted overlay, fuzzy (AND/OR/gamma), coverage layer, deterministic seeds
  validation.py        success/prediction-rate curves, spatial block CV, AUC, sensitivity
  grid.py              AOI grid builder (default 100 m pilot), Malawi clip
apps/web/              React + Vite + TS + Tailwind + MapLibre + TanStack Query + Zustand + Recharts
data/fixtures/         SYNTHETIC test fixtures only (Chitipa gold pilot)
model_templates/       gold_orogenic_draft.json (DRAFT — requires geologist review)
docs/                  architecture.md, data-sources.md, model-templates.md, user-guide.md
infra/                 docker-compose.yml (PostGIS/Redis/MinIO/TiTiler for Docker hosts)
storage/               runtime: sqlite db, grids (.npy), uploads, exports (gitignored)
```

## Spatial conventions
- Storage CRS: EPSG:4326. Analysis CRS: EPSG:32736 (WGS84/UTM 36S).
- Legacy Arc 1950 / UTM 36S = EPSG:20936; Arc 1950 geographic = EPSG:4209.
  Every reprojection is appended to `datasets.processing_history` (see `mwamba_geo.crs`).
- Analysis grid default 100 m pilot, configurable per run. Malawi clip polygon in
  `data/fixtures/malawi_boundary.geojson` (simplified) + bbox check
  lon 32.6–35.9, lat −17.2–−9.3.

## Data labels (mandatory, everywhere)
`VERIFIED | DERIVED | SYNTHETIC | MODEL OUTPUT | REVIEWED`
- Fixtures are SYNTHETIC. Ingested user data defaults to VERIFIED only if source given,
  else unlabeled → shown as submitted. Engine outputs are DERIVED (layers) or
  MODEL OUTPUT (scores/targets). Human sign-off flips to REVIEWED with reviewer+date.
- Frontend shows a badge for every dataset/layer/target; API rejects unlabeled records
  entering analysis without an explicit status.

## Commands
```powershell
# backend (from repo root)
pip install -r requirements.txt
uvicorn apps.api.app.main:app --reload --port 8000
# run tests
pytest apps/api/tests packages/geo/tests -q
# frontend (from apps/web)
npm install
npm run dev        # vite on :5173, proxies /api -> :8000
npm run build      # type-check + production build
npm test           # vitest
```

## Conventions
- Python: ruff + mypy strict on services/lib. Pydantic v2 schemas. No fake numbers:
  every displayed metric is computed from stored data; empty states when absent.
- Scores are relative rankings (0..1), NEVER "probability of economic deposit".
- Missing data is NOT negative evidence: separate coverage layer always computed.
- Determinism: every run stores config + dataset IDs/versions + code version + seed;
  same inputs ⇒ byte-identical grid (tested).
- Secrets only via env (see `.env.example`). No paid APIs required.
- Auth: email+password (bcrypt), JWT, orgs + roles (admin/geologist/analyst/viewer).
  Audit log on imports, runs, reviews, exports.

## Data model (ERD, condensed)
- organisations(id, name) 1—N users(id, email, hash, role, org_id)
- projects(id, org_id, name, commodity, aoi_geojson, grid_m, status_label, created_by)
- datasets(id, org_id, project_id?, name, kind[geology|structure|geophysics|geochem|remotesensing|occurrences|constraints|dem|report],
  format, crs_original, status_label, licence, source_url, provenance JSON, history JSON,
  quality JSON, feature_count, stored_path)
- analysis_runs(id, project_id, method[weighted|fuzzy|wofe|rf|logreg], config JSON, seed,
  code_version, status[queued|running|done|failed], progress, grid_meta JSON, grid_path,
  coverage_path, contributions_path, metrics JSON, created_by)
- targets(id, run_id, rank, area_m2, centroid_lon/lat, centroid_easting/northing,
  mean_score, max_score, coverage, status_label, review_status, evidence JSON, polygon_geojson)
- documents(id, org_id, filename, pages, text_path, status) + extractions(id, doc_id,
  kind, payload JSON, page, snippet, review_state[pending|accepted|rejected])
- validation_results(id, run_id, method, curves JSON, auc, holdout JSON, sensitivity JSON)
- audit_log(id, org_id, user_id, action, entity, entity_id, detail, ts)
- api_keys(id, org_id, user_id, prefix, hash, created)

## Milestone checklist
- [x] M1: auth, projects, Malawi map, upload+validate GeoJSON/CSV, registry, fixtures
- [x] M2: features, overlay+fuzzy, coverage, targets, dossier, exports (verify by running)
- [~] M3: registry seeded+verified reachable; DEM/S2 manual-first pipelines; OCR+review queue (LLM optional)
- [x] M4: spatial CV, curves, holdout, WofE/ML gated (verify by running)
- [~] M5: constraints, PDF, review workflow, demo script (E2E tests still to add)
