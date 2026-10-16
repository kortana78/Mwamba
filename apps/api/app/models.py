"""SQLAlchemy models. Geometries stored as GeoJSON TEXT + centroid lon/lat columns
(SQLite build). A PostGIS backend can replace these columns with Geography types
without changing router/service signatures."""
from __future__ import annotations
import datetime as dt
import uuid

from sqlalchemy import String, Text, Float, Integer, Boolean, DateTime, ForeignKey, JSON
from sqlalchemy.orm import Mapped, mapped_column, relationship
from .database import Base

STATUS_LABELS = ("VERIFIED", "DERIVED", "SYNTHETIC", "MODEL OUTPUT", "REVIEWED", "UNVERIFIED")


def _uid() -> str:
    return uuid.uuid4().hex[:12]


def _now() -> dt.datetime:
    return dt.datetime.now(dt.timezone.utc)


class Organisation(Base):
    __tablename__ = "organisations"
    id: Mapped[str] = mapped_column(String(16), primary_key=True, default=_uid)
    name: Mapped[str] = mapped_column(String(200))
    created_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), default=_now)
    users: Mapped[list["User"]] = relationship(back_populates="org")


class User(Base):
    __tablename__ = "users"
    id: Mapped[str] = mapped_column(String(16), primary_key=True, default=_uid)
    email: Mapped[str] = mapped_column(String(320), unique=True, index=True)
    password_hash: Mapped[str] = mapped_column(String(256))
    role: Mapped[str] = mapped_column(String(32), default="viewer")  # admin|geologist|analyst|viewer
    org_id: Mapped[str] = mapped_column(ForeignKey("organisations.id"))
    created_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), default=_now)
    org: Mapped[Organisation] = relationship(back_populates="users")


class Project(Base):
    __tablename__ = "projects"
    id: Mapped[str] = mapped_column(String(16), primary_key=True, default=_uid)
    org_id: Mapped[str] = mapped_column(ForeignKey("organisations.id"), index=True)
    name: Mapped[str] = mapped_column(String(200))
    commodity: Mapped[str] = mapped_column(String(32), default="Au")
    aoi_geojson: Mapped[dict] = mapped_column(JSON)
    grid_m: Mapped[float] = mapped_column(Float, default=100.0)
    status_label: Mapped[str] = mapped_column(String(32), default="VERIFIED")
    visibility: Mapped[str] = mapped_column(String(16), default="private")  # public|private
    is_demo: Mapped[bool] = mapped_column(Boolean, default=False)  # True = sandbox runs allowed here
    created_by: Mapped[str] = mapped_column(String(16))
    created_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), default=_now)


class Dataset(Base):
    __tablename__ = "datasets"
    id: Mapped[str] = mapped_column(String(16), primary_key=True, default=_uid)
    org_id: Mapped[str] = mapped_column(ForeignKey("organisations.id"), index=True)
    project_id: Mapped[str | None] = mapped_column(ForeignKey("projects.id"), nullable=True, index=True)
    name: Mapped[str] = mapped_column(String(300))
    kind: Mapped[str] = mapped_column(String(32), index=True)
    format: Mapped[str] = mapped_column(String(32))
    crs_original: Mapped[str] = mapped_column(String(32), default="EPSG:4326")
    status_label: Mapped[str] = mapped_column(String(32), default="VERIFIED")
    visibility: Mapped[str] = mapped_column(String(16), default="private")  # public|private
    licence: Mapped[str] = mapped_column(String(300), default="")
    source_url: Mapped[str] = mapped_column(String(600), default="")
    provenance: Mapped[dict] = mapped_column(JSON, default=dict)
    processing_history: Mapped[list] = mapped_column(JSON, default=list)
    quality: Mapped[dict] = mapped_column(JSON, default=dict)
    feature_count: Mapped[int] = mapped_column(Integer, default=0)
    stored_path: Mapped[str] = mapped_column(String(600), default="")
    created_by: Mapped[str] = mapped_column(String(16), default="")
    created_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), default=_now)


class AnalysisRun(Base):
    __tablename__ = "analysis_runs"
    id: Mapped[str] = mapped_column(String(16), primary_key=True, default=_uid)
    project_id: Mapped[str] = mapped_column(ForeignKey("projects.id"), index=True)
    method: Mapped[str] = mapped_column(String(32), default="weighted")  # weighted|fuzzy|wofe|logreg
    config: Mapped[dict] = mapped_column(JSON, default=dict)
    seed: Mapped[int] = mapped_column(Integer, default=42)
    code_version: Mapped[str] = mapped_column(String(32), default="0.1.0")
    status: Mapped[str] = mapped_column(String(32), default="queued")  # queued|running|done|failed
    progress: Mapped[float] = mapped_column(Float, default=0.0)
    error: Mapped[str] = mapped_column(Text, default="")
    grid_meta: Mapped[dict] = mapped_column(JSON, default=dict)
    grid_path: Mapped[str] = mapped_column(String(600), default="")
    coverage_path: Mapped[str] = mapped_column(String(600), default="")
    contributions_path: Mapped[str] = mapped_column(String(600), default="")
    metrics: Mapped[dict] = mapped_column(JSON, default=dict)
    dataset_ids: Mapped[list] = mapped_column(JSON, default=list)
    created_by: Mapped[str] = mapped_column(String(16), default="")
    created_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), default=_now)


class Target(Base):
    __tablename__ = "targets"
    id: Mapped[str] = mapped_column(String(16), primary_key=True, default=_uid)
    run_id: Mapped[str] = mapped_column(ForeignKey("analysis_runs.id"), index=True)
    rank: Mapped[int] = mapped_column(Integer, default=0)
    area_m2: Mapped[float] = mapped_column(Float, default=0.0)
    centroid_lon: Mapped[float] = mapped_column(Float, default=0.0)
    centroid_lat: Mapped[float] = mapped_column(Float, default=0.0)
    centroid_easting: Mapped[float] = mapped_column(Float, default=0.0)
    centroid_northing: Mapped[float] = mapped_column(Float, default=0.0)
    mean_score: Mapped[float] = mapped_column(Float, default=0.0)
    max_score: Mapped[float] = mapped_column(Float, default=0.0)
    coverage: Mapped[float] = mapped_column(Float, default=0.0)
    status_label: Mapped[str] = mapped_column(String(32), default="MODEL OUTPUT")
    review_status: Mapped[str] = mapped_column(String(32), default="Proposed")
    reviewer: Mapped[str] = mapped_column(String(200), default="")
    review_notes: Mapped[str] = mapped_column(Text, default="")
    evidence: Mapped[dict] = mapped_column(JSON, default=dict)
    polygon_geojson: Mapped[dict] = mapped_column(JSON, default=dict)


class Document(Base):
    __tablename__ = "documents"
    id: Mapped[str] = mapped_column(String(16), primary_key=True, default=_uid)
    org_id: Mapped[str] = mapped_column(ForeignKey("organisations.id"), index=True)
    filename: Mapped[str] = mapped_column(String(300))
    pages: Mapped[int] = mapped_column(Integer, default=0)
    text_path: Mapped[str] = mapped_column(String(600), default="")
    status: Mapped[str] = mapped_column(String(32), default="stored")
    created_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), default=_now)


class Extraction(Base):
    __tablename__ = "extractions"
    id: Mapped[str] = mapped_column(String(16), primary_key=True, default=_uid)
    doc_id: Mapped[str] = mapped_column(ForeignKey("documents.id"), index=True)
    kind: Mapped[str] = mapped_column(String(64), default="occurrence")
    payload: Mapped[dict] = mapped_column(JSON, default=dict)
    page: Mapped[int] = mapped_column(Integer, default=1)
    snippet: Mapped[str] = mapped_column(Text, default="")
    review_state: Mapped[str] = mapped_column(String(32), default="pending")
    created_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), default=_now)


class ValidationResult(Base):
    __tablename__ = "validation_results"
    id: Mapped[str] = mapped_column(String(16), primary_key=True, default=_uid)
    run_id: Mapped[str] = mapped_column(ForeignKey("analysis_runs.id"), index=True)
    method: Mapped[str] = mapped_column(String(64), default="holdout")
    curves: Mapped[dict] = mapped_column(JSON, default=dict)
    auc: Mapped[float | None] = mapped_column(Float, nullable=True)
    holdout: Mapped[dict] = mapped_column(JSON, default=dict)
    sensitivity: Mapped[dict] = mapped_column(JSON, default=dict)
    created_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), default=_now)


class AuditLog(Base):
    __tablename__ = "audit_log"
    id: Mapped[str] = mapped_column(String(16), primary_key=True, default=_uid)
    org_id: Mapped[str] = mapped_column(String(16), index=True)
    user_id: Mapped[str] = mapped_column(String(16), index=True)
    action: Mapped[str] = mapped_column(String(64), index=True)
    entity: Mapped[str] = mapped_column(String(64))
    entity_id: Mapped[str] = mapped_column(String(64))
    detail: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), default=_now)


class ApiKey(Base):
    __tablename__ = "api_keys"
    id: Mapped[str] = mapped_column(String(16), primary_key=True, default=_uid)
    org_id: Mapped[str] = mapped_column(String(16), index=True)
    user_id: Mapped[str] = mapped_column(String(16))
    prefix: Mapped[str] = mapped_column(String(16))
    key_hash: Mapped[str] = mapped_column(String(256))
    created_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), default=_now)
