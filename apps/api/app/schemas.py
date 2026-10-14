"""Pydantic v2 schemas."""
from __future__ import annotations
from typing import Literal
from pydantic import BaseModel, Field

StatusLabel = Literal["VERIFIED", "DERIVED", "SYNTHETIC", "MODEL OUTPUT", "REVIEWED", "UNVERIFIED"]
DatasetKind = Literal["geology", "structure", "geophysics", "geochem", "remotesensing",
                      "occurrences", "constraints", "dem", "report"]

#: Commodity codes with full names (wizard dropdown; enforced on project create).
COMMODITIES: dict[str, str] = {
    "Au": "Gold",
    "C": "Graphite",
    "REE": "Rare Earth Elements",
    "Nb": "Niobium",
    "Ti": "Rutile (Titanium)",
    "U": "Uranium",
}

#: Malawi bbox (lon/lat). AOIs must fall inside; measured in degrees.
MALAWI_BBOX = (32.6, -17.2, 35.9, -9.3)


def validate_aoi(obj: dict) -> dict:
    """Normalise + validate a project AOI. Returns the Polygon/MultiPolygon dict.

    Raises ValueError with a plain message when: not a polygon, empty, outside
    Malawi, or absurdly large (> 1/4 of Malawi). Never silently fixes input.
    """
    if not isinstance(obj, dict):
        raise ValueError("AOI must be a GeoJSON object")
    geom = obj.get("geometry", obj) if obj.get("type") == "Feature" else obj
    if not isinstance(geom, dict) or geom.get("type") not in ("Polygon", "MultiPolygon"):
        raise ValueError("AOI must be a GeoJSON Polygon/MultiPolygon (draw, pick a district, or upload)")
    try:
        from shapely.geometry import shape as _shape
        poly = _shape(geom)
    except Exception:
        raise ValueError("AOI geometry is unparseable")
    if poly.is_empty:
        raise ValueError("AOI polygon is empty")
    if not poly.is_valid:
        raise ValueError("AOI polygon is self-intersecting; redraw it")
    minx, miny, maxx, maxy = poly.bounds
    m0, n0, m1, n1 = MALAWI_BBOX
    if maxx < m0 or minx > m1 or maxy < n0 or miny > n1:
        raise ValueError(f"AOI {poly.bounds} falls outside Malawi ({MALAWI_BBOX}). Draw inside Malawi.")
    # area sanity: Malawi ~118 000 km²; refuse AOIs larger than ~30 000 km²
    area_km2 = abs(poly.area) * (111.32 ** 2)
    if area_km2 > 30000:
        raise ValueError(f"AOI is {area_km2:,.0f} km² — larger than any district. Draw a smaller area.")
    if area_km2 < 0.01:
        raise ValueError("AOI is vanishingly small; draw a larger area.")
    return {"type": geom["type"], "coordinates": geom["coordinates"]}


class RegisterIn(BaseModel):
    email: str = Field(min_length=3, max_length=320)
    password: str = Field(min_length=8, max_length=128)
    org_name: str = Field(min_length=1, max_length=200)
    role: str = "viewer"


class LoginIn(BaseModel):
    email: str = Field(min_length=3, max_length=320)
    password: str


class TokenOut(BaseModel):
    access_token: str
    token_type: str = "bearer"


class UserOut(BaseModel):
    id: str
    email: str
    role: str
    org_id: str


class ProjectIn(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    commodity: str = "Au"
    aoi_geojson: dict
    grid_m: float = 100.0
    # NOTE: no status_label input — project status derives from its datasets.


class DatasetIn(BaseModel):
    name: str
    kind: str
    project_id: str | None = None
    crs_original: str = "EPSG:4326"
    status_label: StatusLabel = "VERIFIED"
    licence: str = ""
    source_url: str = ""


class RunIn(BaseModel):
    method: Literal["weighted", "fuzzy", "wofe", "logreg"] = "weighted"
    config: dict = Field(default_factory=dict)
    seed: int = 42
    dataset_ids: list[str] | None = None
    holdout_fraction: float = 0.3


class ReviewIn(BaseModel):
    review_status: Literal["Proposed", "Under review", "Field verified", "Rejected", "Advanced"]
    reviewer: str = ""
    review_notes: str = ""


class ExtractionReviewIn(BaseModel):
    review_state: Literal["pending", "accepted", "rejected"]


class CitationIn(BaseModel):
    author: str = ""
    year: int | None = None
    title: str = ""
    page_figure: str = ""


class CitedOccurrenceIn(BaseModel):
    """Literature occurrence entry. VERIFIED only with a full citation
    (author + year + title); otherwise stored UNVERIFIED."""
    name: str = Field(min_length=1, max_length=300)
    commodity: str = "Au"
    project_id: str | None = None
    # coordinates in any supported CRS (declared via crs_original, default 4326)
    x: float
    y: float
    crs_original: str = "EPSG:4326"
    accuracy_m: float | None = None
    citation: CitationIn = Field(default_factory=CitationIn)
    notes: str = ""

    def citation_complete(self) -> bool:
        c = self.citation
        return bool(c.author.strip() and c.title.strip() and c.year)

    def citation_text(self) -> str:
        c = self.citation
        bits = [c.author.strip(), f"({c.year})" if c.year else "",
                c.title.strip(), c.page_figure.strip()]
        return " ".join(b for b in bits if b)
