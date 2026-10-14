# Manual data download guide (free sources, no paid APIs)

Mwamba has no paid data budget: every layer below is free. Download the files
on your own machine, then import them on the **Ingest** page (or via
`POST /ingest/...`). Record the source URL + retrieval date on import so the
provenance badge stays honest.

Status labels on import: user files default to **VERIFIED** only when you give
a source; WDPA imports must be marked **restricted** (local use only).

## 1. OpenStreetMap — Geofabrik Malawi shapefile ZIP

- **URL:** https://download.geofabrik.de/africa/malawi.html
- Click the `.shp.zip` (e.g. `malawi-latest-free.shp.zip`). Inside are one-shapefile-per-theme zips.
- **Import:** Ingest → **shapefile** tab → upload the single-theme zip (one `.shp` layer per zip), kind `structure` (roads/rivers as lineaments context) or `constraints` (towns/schools exclusion). CRS auto-detect handles WGS84; leave `crs_original=auto`.
- Tested path: `POST /ingest/shapefile` (zipped shapefile reader, Malawi UTM36S auto-detect).

## 2. Sentinel-2 bands — Copernicus Browser

- **URL:** https://browser.dataspace.copernicus.eu/ (free account required to download).
- Draw your AOI in Malawi → search Sentinel-2 L2A → pick a low-cloud scene → download bands **B02, B04, B08, B11, B12** (separate JP2/TIFF files).
- Stack them into one multiband GeoTIFF in band order B2,B4,B8,B11,B12, e.g.:
  `gdal_merge.py -separate -o s2_stack.tif B02.tif B04.tif B08.tif B11.tif B12.tif`
  (if your downloads arrive in a different order, set the `band_B*` fields on import to match).
- **Import:** Ingest → **sentinel2** tab (`POST /ingest/sentinel2`). The server computes:
  - iron-oxide = **B4/B2**, clay/hydroxyl = **B11/B12**, NDVI = (B8−B4)/(B8+B4) with an NDVI>0.4 vegetation mask —
  and registers each as a **DERIVED** `remotesensing` dataset with its recipe. They feed the
  `alteration_or_geochem` evidence group automatically.
- If `gdal_merge.py` is unavailable, upload any single-band ratio you computed yourself as `remotesensing` GeoTIFF — but it only becomes evidence when it carries a `derived_ratio` recipe (use the sentinel2 endpoint).

## 3. Protected areas — WDPA Malawi shapefile (RESTRICTED)

- **URL:** https://www.protectedplanet.net/ → search “Malawi” → download (shapefile). Requires accepting the WDPA licence.
- **Licence: NO redistribution.** Store under `data/wdpa/` (git-ignored), import with **restricted=true**
  (`POST /ingest/shapefile` with `restricted=true`, kind `constraints`).
- Restricted datasets render on your own map but return **403** on `/datasets/{id}/geojson` and are **excluded from project summaries and exports**. Never commit them to git.

## 4. USGS generalised Africa geology + faults

- **URLs:** https://mrdata.usgs.gov/mrds/ (occurrence search by bounding box) and the USGS Africa geologic/geophysical compilations via https://mrdata.usgs.gov/geology/africa/ (if a link is dead, search “USGS Africa geology GIS” — use whatever file the survey currently serves and record its exact URL on import).
- **Import:** geology polygons → kind `geology` (then assign per-unit favourability scores 0..1 in the run config `lithology_scores`); fault lines → kind `structure`. Both accept GeoJSON or zipped shapefile; declare or auto-detect CRS.
- Occurrence sweeps (like the seeded `usgs_mrds_chitipa.geojson`, US public domain) import as kind `occurrences`. Non-matching commodities are excluded from validation and counted (`n_skipped_other_commodity` in run metrics) — a stone record never validates a gold model.

## 5. Copernicus DEM (already seeded for Chitipa)

- Source: https://copernicus-dem-30m.s3.eu-central-1.amazonaws.com/ (GLO-30, free with attribution).
- The seeded `data/real/chitipa_dem_30m.tif` crop + `manifest.json` document the recipe. New crops: download the S10E033 (or neighbour) tile, crop to your AOI, import as kind `dem` GeoTIFF. The engine derives slope + **lineaments** (multi-azimuth hillshade, DERIVED “unverified structural proxy”) + **drainage** automatically.
