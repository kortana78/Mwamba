"""Async SQLite engine + session. Repository layer isolated here so PostGIS can
replace it later without touching routers/services."""
from __future__ import annotations
import os
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker, AsyncSession
from sqlalchemy.orm import DeclarativeBase
from .config import settings


class Base(DeclarativeBase):
    pass


def _db_url() -> str:
    # Render Postgres later via DATABASE_URL; local/ephemeral via MWAMBA_DB_URL.
    # database.py must stay backend-agnostic: PostGIS can replace the engine here.
    try:
        from .config import settings as _s
        url = _s.db_url()
    except Exception:
        url = os.environ.get("DATABASE_URL", "") or os.environ.get("MWAMBA_DB_URL", "")
        if not url:
            url = "sqlite+aiosqlite:///./storage/mwamba.db"
    else:
        url = os.environ.get("DATABASE_URL", "") or os.environ.get("MWAMBA_DB_URL", "") or url
        if url.startswith("postgres://"):
            url = url.replace("postgres://", "postgresql+asyncpg://", 1)
        elif url.startswith("postgresql://") and "+asyncpg" not in url:
            url = url.replace("postgresql://", "postgresql+asyncpg://", 1)
    return url


engine = create_async_engine(_db_url(), echo=False, future=True)
SessionLocal = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)


async def get_db():
    async with SessionLocal() as s:
        yield s


async def init_db() -> None:
    from . import models  # noqa: F401  (register tables)
    storage = os.environ.get("MWAMBA_STORAGE_DIR", settings.MWAMBA_STORAGE_DIR)
    os.makedirs(storage, exist_ok=True)
    for sub in ("uploads", "grids", "exports", "texts"):
        os.makedirs(os.path.join(storage, sub), exist_ok=True)
    # SQLite cannot create parent dirs itself — ensure the DB file's parent exists
    # BEFORE connecting (otherwise "unable to open database file" on first boot).
    db_url = _db_url()
    if db_url.startswith("sqlite"):
        path = db_url.split(":///", 1)[-1].split("?")[0].replace("/", os.sep)
        parent = os.path.dirname(os.path.abspath(path))
        if parent:
            os.makedirs(parent, exist_ok=True)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
        await conn.run_sync(_migrate_sqlite)


def _migrate_sqlite(sync_conn) -> None:
    """Lightweight additive migration for pre-existing SQLite files
    (new columns only; fresh DBs already have them via create_all)."""
    import sqlalchemy as _sa
    insp = _sa.inspect(sync_conn)
    wanted = {"projects": {"visibility": "VARCHAR(16) DEFAULT 'private'",
                           "is_demo": "BOOLEAN DEFAULT 0"},
              "datasets": {"visibility": "VARCHAR(16) DEFAULT 'private'"}}
    for table, cols in wanted.items():
        if table not in insp.get_table_names():
            continue
        existing = {c["name"] for c in insp.get_columns(table)}
        for col, ddl in cols.items():
            if col not in existing:
                sync_conn.exec_driver_sql(f"ALTER TABLE {table} ADD COLUMN {col} {ddl}")
