# Deploy Mwamba to Render (Blueprint)

Live prototype: Python API + static Vite frontend, SQLite seeded on startup.
Filesystem on the free tier is **ephemeral**: the DB is created and seeded on
every boot (demo projects + fixtures + real DEM crop), uploads and new runs
live temporarily. The UI shows a banner:
"Live demo — uploads and new runs reset when the server restarts."

## 1. Prerequisites (you do these)

- A GitHub account + the `mwamba` repo pushed (private is fine).
- A Render account (https://render.com).
- `gh` CLI authenticated locally **only if** you want the one-line repo create:
  `gh auth login` (never paste tokens into chat or files).

## 2. Push the repo

```powershell
# from the repo root (Windows; git must be installed)
git init
git add .
git commit -m "Mwamba live prototype"
gh repo create mwamba --private --source=. --push
```

If `gh` is not authenticated, STOP and run `gh auth login` first.
Never commit `.env`, `*.db`, `storage/`, or `data/real/copernicus_dem_S10E033.tif`
(the raw 40 MB tile — re-download below). The 2.6 MB AOI crop
`data/real/chitipa_dem_30m.tif` IS committed (Copernicus attribution).

## 3. New Blueprint

1. Render Dashboard → New → **Blueprint** → connect the `mwamba` repo.
2. Render reads `render.yaml` and proposes two services:
   - `mwamba-api` (Python web service, plan: free)
   - `mwamba-web` (static site, plan: free)
3. Set env vars (Dashboard → service → Environment):
   - API **required**: `ADMIN_EMAIL`, `ADMIN_PASSWORD` (pick strong values),
     `FRONTEND_ORIGIN` (the `https://<mwamba-web>.onrender.com` URL — update
     after the first deploy, then redeploy the API so CORS allows it).
   - API **recommended**: `DEMO_USER_EMAIL`, `DEMO_USER_PASSWORD`,
     `JWT_SECRET` (auto-generated via `generateValue`), `DATABASE_URL`
     (leave empty for ephemeral SQLite; set a Postgres URL later per
     `docs/postgis-migration.md`).
   - API **optional**: `MAX_UPLOAD_MB` (default 100), `MWAMBA_MAX_GRID_CELLS`
     (default 2500000), `REDIS_URL` (empty = in-process BackgroundTasks).
   - Web: `VITE_API_URL` auto-points at the API via `fromService.host`
     (the frontend prepends `https://` when the scheme is missing). If the API
     URL changes, update and redeploy the static site.
4. Deploy. First API boot takes a few minutes (pip + rasterio wheels).

## 4. Verify (record results here + README)

- [ ] `https://<mwamba-api>.onrender.com/api/health` returns 200 `{"ok": true}`.
- [ ] Open the frontend URL → "Try the demo" button visible.
- [ ] Full demo path on the LIVE site: Try demo → synthetic project
      ("Chitipa Gold — Synthetic demo") → Models → Run → Targets (1–20 ranked)
      → dossier → dossier PDF → Validation → export (geojson/csv/kml).
- [ ] Open "Chitipa Gold — Real data (evidence incomplete)" → Models shows
      `INSUFFICIENT EVIDENCE — not a targeting result`, Targets lists zero
      ranked targets, project badge reads `EVIDENCE INCOMPLETE`.
- [ ] Cold start: first click after idle shows
      "Waking the server — up to a minute" instead of an error.

## 5. Known limitations (live)

- Ephemeral filesystem: uploads/new runs vanish on restart (banner shown).
- In-process jobs: keep runs small (pilot AOI, 100–200 m grid, timeout 240 s
  with a clear error). Celery/Redis path activates when `REDIS_URL` is set.
- SQLite only: set `DATABASE_URL` to Postgres later (see migration doc).
- Demo account is `analyst` role (can run, cannot reach Admin). Other viewers
  are read-only in `DEMO_MODE`.
- Secrets: `git grep -i -E "secret|password|api_key|token"` before push;
  seeded passwords come only from env vars in production.

## Deployment log

| Date (UTC) | Frontend URL | API URL | Verified by | Notes |
|---|---|---|---|---|
| _pending — fill after first deploy_ | | | | |
