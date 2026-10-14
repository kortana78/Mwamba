# SQLite → PostGIS migration plan

Current: SQLite + GeoJSON-text geometries (`apps/api/app/database.py`, `models.py`).
Target: PostgreSQL 16 + PostGIS (see `infra/docker-compose.yml`).

## Steps (in order, each independently shippable)
1. Add `GeoAlchemy2` + `asyncpg` (already present) to requirements; add a
   `MWAMBA_DB_URL=postgresql+asyncpg://…` branch in `database.py` that creates the
   same engine/session interface. No router/service changes (they only use the
   session + model attributes).
2. Alembic: `alembic init infra/migrations`, autogenerate from `models.py`, with a
   custom step converting `TEXT` GeoJSON columns → `Geography('GEOMETRY', 4326)`
   (load via `ST_GeomFromGeoJSON`). Centroid columns become generated
   (`ST_Y/ST_X`) or populated by trigger.
3. Data migration script `scripts/sqlite_to_postgis.py`: copy rows table by table;
   grids (`.npy`) and uploads move to MinIO/S3 (paths already abstracted as
   `stored_path`/`grid_path` — prefix with bucket URL).
4. Raster tiles: upload COGs to MinIO, point TiTiler at the bucket, replace the
   PNG data-URL overlay path with tile URLs (frontend `MapView` already isolates
   overlay sources in one `refresh()` function).
5. Cut over: set `MWAMBA_DB_URL`, run `alembic upgrade head`, re-run the pytest
   suite against Postgres (tests read `MWAMBA_DB_URL` from env — no code change).

## Why this order is safe
Repository code never imports PostGIS types; geometry lives behind two columns
(GeoJSON text + lon/lat) that map 1:1 onto Geography + generated centroids.
Determinism tests (byte-identical grids) pin engine behaviour across the move.
