# Data sources

Live registry: `GET /sources/registry`. Reachability is verified on demand
(`POST /sources/registry/verify`, HEAD with timeout) — a source is automated only
after a live check passes.

## Verified 2026-10-13 (this host, recorded in `data/real/manifest.json`)
- **Copernicus DEM GLO-30**: tile `S10E033` downloaded (40.5 MB) from the public AWS
  bucket, cropped to Chitipa AOI+margin → `data/real/chitipa_dem_30m.tif`
  (972×1008, 30 m, elev 1010–2116 m, mean 1271 m). Licence: Copernicus (free,
  attribution). Seeded as VERIFIED DEM dataset in the real-data project.
- **USGS MRDS**: `search-bbox.php` verified live. Pilot AOI → exactly **1 record
  (Chitipa #10023348, dimension-STONE prospect, not gold)**. District sweep →
  plus **Chasweta Nb prospect #10183392** north of AOI. **Zero public USGS gold
  occurrences** in/near the pilot AOI — recorded, not hidden. Seeded VERIFIED+cited.
- **Sentinel-2 L2A / PC STAC**: search verified live; dry-season scene
  `S2B_MSIL2A_20240927T074609` (cloud 0.008%) identified. Asset download needs a
  free PC account (unsigned → HTTP 409). MANUAL IMPORT with the saved query below.
- **Overpass (OSM)**: status endpoint reachable, interpreter 400/504 on two mirrors
  at fetch time (overloaded). Queries saved below; retry documented. Constraints
  module shows an honest empty state meanwhile.
- **geoBoundaries MWI ADM2**: downloaded (5.7 MB, CC-BY 3.0 IGO); slimmed picker at
  `apps/web/public/districts.json`; Chitipa polygon available for AOI.
- **Protected areas / WDPA**: registration required → manual import only.

## Saved queries (retry / manual import)
- Overpass roads: `[out:geojson];way[highway](-9.86,33.20,-9.69,33.38);out geom;`
- Overpass water: `[out:geojson];(way[natural=water](-9.86,33.20,-9.69,33.38);way[water](-9.86,33.20,-9.69,33.38););out geom;`
- Overpass settlements: `[out:geojson];(node[place](-9.86,33.20,-9.69,33.38);way[place](-9.86,33.20,-9.69,33.38););out geom;`
  → Ingest as `kind=constraints`.
- S2 STAC: `POST https://planetarycomputer.microsoft.com/api/stac/v1/search`
  `{"collections":["sentinel-2-l2a"],"bbox":[33.20,-9.86,33.38,-9.69],`
  `"datetime":"2024-06-01/2024-10-31","query":{"eo:cloud_cover":{"lt":20}}}`
  → download B04/B08/B11/B12+SCL (SAS), derive Fe-oxide (B04/B02), clay (B11/B12),
  NDVI mask → Ingest › geotiff (`kind=remotesensing`).

## Open, automatable (manual-import-first in this build)
| Source | Use | Licence |
|---|---|---|
| Copernicus DEM GLO-30 (`dataspace.copernicus.eu`) | slope, drainage | Copernicus, free + attribution |
| Sentinel-2 L2A via Planetary Computer STAC | iron-oxide / clay ratios, NDVI mask | Copernicus, free |
| ASTER L1T (`earthdata.nasa.gov`) | alteration (where licensing allows) | registration, check per scene |
| USGS mineral records (`mrdata.usgs.gov`) | occurrence cross-check | US public domain |
| geoBoundaries | Malawi clip polygon | check CC-BY terms; simplified clip ships as SYNTHETIC fixture |
| OpenStreetMap | settlements, water, roads (constraints) | ODbL, attribute |

## Manual import (restricted / by request) — never scraped
GEMMAP maps, GSD airborne magnetics/radiometrics, mining cadastre licences.
Upload licensed files via the Ingest wizard; licence + provenance are recorded and
the constraints module flags overlaps automatically.

## Literature
Chitipa airborne geophysics for gold (published): stored as a reference linked from
the gold model template. Obtain data from authors/GSD.

## Pipelines
- DEM: download AOI tile → upload → slope/drainage derived layers (recipe stored).
- Sentinel-2: export ratios + NDVI mask → upload COG → documented; auto STAC fetch planned.
- Reports: PDF → text (pypdf; ocrmypdf documented for scans) → candidate extraction →
  REVIEW QUEUE → accept/edit/reject. LLM extraction optional (`LLM_EXTRACTION_ENABLED`),
  never enters analysis without human review.

## What ships in git vs what you re-download

| File | In git? | Licence | Re-download |
|---|---|---|---|
| `data/real/chitipa_dem_30m.tif` (2.6 MB AOI crop) | ✅ yes | Copernicus (free, attribution) | — |
| `data/real/usgs_mrds_chitipa.geojson` | ✅ yes | US public domain | `https://mrdata.usgs.gov/mrds/search-bbox.php?xmin=33.20&ymin=-9.86&xmax=33.38&ymax=-9.69` |
| `data/real/malawi_districts_adm2.geojson` (5.6 MB) | ✅ yes | CC-BY 3.0 IGO | `https://github.com/wmgeolab/geoBoundaries/raw/9469f09/releaseData/gbOpen/MWI/ADM2/geoBoundaries-MWI-ADM2.geojson` |
| `data/real/manifest.json` | ✅ yes | — | — |
| `data/real/copernicus_dem_S10E033.tif` (~40 MB raw tile) | ❌ excluded (`.gitignore`) | Copernicus (free, attribution) | `https://copernicus-dem-30m.s3.eu-central-1.amazonaws.com/Copernicus_DSM_COG_10_S10_00_E033_00_DEM/Copernicus_DSM_COG_10_S10_00_DEM.tif` |
| WDPA / restricted (`data/wdpa/`, `data/restricted/`) | ❌ never | per-dataset (registration) | Manual import via Ingest → shapefile/geopackage as `kind=constraints` |
| `storage/` (sqlite db, grids, uploads, exports) | ❌ never | — | Created + seeded on startup |

Nothing over 50 MB is committed. Large/raw downloads stay local.
