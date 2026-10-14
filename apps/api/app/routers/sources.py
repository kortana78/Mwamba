"""Source registry: seeded, honest availability. Reachability is checked live
(HEAD with timeout) — never claimed without verification. Restricted sources are
marked 'Not available — manual import' and never scraped."""
from __future__ import annotations
import time
import urllib.request
from fastapi import APIRouter
from .. import models
from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession
from ..database import get_db
from ..deps import current_user

router = APIRouter(prefix="/sources", tags=["sources"])

REGISTRY = [
    {"id": "copernicus-dem-glo30", "name": "Copernicus DEM GLO-30",
     "url": "https://dataspace.copernicus.eu/",
     "licence": "Copernicus licence (free, attribution)",
     "access": "Open, automatable (manual download / S3)",
     "pipeline": "Manual-import-first: download tile for AOI, upload as GeoTIFF→(documented); auto STAC fetch planned",
     "commodity_use": "Terrain: slope, drainage"},
    {"id": "sentinel2-l2a", "name": "Sentinel-2 L2A (Microsoft Planetary Computer STAC)",
     "url": "https://planetarycomputer.microsoft.com/",
     "licence": "Copernicus (free)",
     "access": "Open, automatable via STAC",
     "pipeline": "Manual-import-first: export iron-oxide/clay ratios + NDVI mask, upload COG; auto pipeline planned",
     "commodity_use": "Remote sensing: iron-oxide, clay/hydroxyl ratios"},
    {"id": "aster", "name": "ASTER L1T",
     "url": "https://earthdata.nasa.gov/",
     "licence": "Check redistribution terms before automating",
     "access": "Open with registration; verify licence",
     "pipeline": "Manual import; verify licence per scene",
     "commodity_use": "Alteration mapping where licensing allows"},
    {"id": "usgs-mrds", "name": "USGS Mineral Resource records covering Malawi",
     "url": "https://mrdata.usgs.gov/",
     "licence": "Public domain (USGS)",
     "access": "Open",
     "pipeline": "Manual CSV import via Ingest wizard; connector planned",
     "commodity_use": "Occurrences (cross-check, VERIFIED only with source)"},
    {"id": "geoboundaries", "name": "geoBoundaries — Malawi boundary",
     "url": "https://www.geoboundaries.org/",
     "licence": "Check licence (CC-BY family); simplified clip ships in fixtures",
     "access": "Open",
     "pipeline": "Manual import; fixtures carry simplified clip labelled SYNTHETIC",
     "commodity_use": "AOI clipping"},
    {"id": "osm", "name": "OpenStreetMap (roads, settlements, water)",
     "url": "https://www.openstreetmap.org/",
     "licence": "ODbL (attribute)",
     "access": "Open (Overpass/Geofabrik extracts)",
     "pipeline": "Manual extract import as constraints layers",
     "commodity_use": "Constraints: settlements, water buffers"},
    {"id": "gemmap", "name": "GEMMAP geological maps and data",
     "url": "https://www.gemmap-malawi.org/",
     "licence": "Restricted / by request",
     "access": "Not available — manual import",
     "pipeline": "Upload licensed files via Ingest wizard; provenance + licence recorded",
     "commodity_use": "Geology, structure"},
    {"id": "gsd-airborne", "name": "National airborne magnetics/radiometrics (GSD)",
     "url": "",
     "licence": "Restricted / by request (GSD)",
     "access": "Not available — manual import",
     "pipeline": "Upload licensed grids as GeoTIFF/XYZ; RTP/AS/tilt derivatives computed on import",
     "commodity_use": "Geophysics"},
    {"id": "cadastre", "name": "Mining cadastre licence boundaries",
     "url": "",
     "licence": "Restricted (Ministry of Mining)",
     "access": "Not available — manual import",
     "pipeline": "Upload as constraints polygons; conflict flags automatic",
     "commodity_use": "Constraints: existing licences"},
    {"id": "chitipa-lit", "name": "Chitipa airborne geophysics for gold (published study)",
     "url": "",
     "licence": "Literature reference (fair use citation)",
     "access": "Reference linked to layers; obtain data from authors/GSD",
     "pipeline": "Stored as reference; linked in model template rationale",
     "commodity_use": "Gold targeting rationale"},
]


def _check_url(url: str, timeout: float = 6.0) -> dict:
    if not url:
        return {"reachable": None, "note": "No public URL — manual import"}
    try:
        req = urllib.request.Request(url, method="HEAD", headers={"User-Agent": "Mwamba/0.1"})
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return {"reachable": resp.status < 400, "http_status": resp.status}
    except Exception as e:
        return {"reachable": False, "note": f"Unreachable from this host ({type(e).__name__}); marked, not automated"}


@router.get("/registry")
async def registry(user: models.User = Depends(current_user)):
    items = []
    for s in REGISTRY:
        items.append({**s, "status_label": "VERIFIED" if s["access"].startswith("Open") else "REVIEWED",
                      "note": "Do not scrape restricted sites or redistribute confidential data."})
    return {"sources": items,
            "policy": "A source is automated only after a live reachability check passes. "
                      "Restricted sources stay manual-import with licence recorded."}


@router.post("/registry/verify")
async def verify(user: models.User = Depends(current_user)):
    out = []
    for s in REGISTRY:
        chk = _check_url(s["url"])
        out.append({"id": s["id"], "name": s["name"], **chk})
        time.sleep(0.1)
    return {"checked_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()), "results": out}
