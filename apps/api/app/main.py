"""Mwamba API — Malawi Mineral Exploration Intelligence Platform."""
from __future__ import annotations
import logging
from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
import structlog
from slowapi import _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded

from .config import settings
from .database import init_db
from .seed import seed
from .ratelimit import limiter
from .routers import auth, projects, datasets, ingest, runs, targets, validation, reports, sources, admin

log = structlog.get_logger()


@asynccontextmanager
async def lifespan(app: FastAPI):
    logging.basicConfig(level=logging.INFO)
    await init_db()
    info = await seed()
    log.info("mwamba_startup", seed=info)
    yield


app = FastAPI(title="Mwamba API",
              description="Malawi Mineral Exploration Intelligence Platform. "
                          "Scores are relative rankings, never deposit probabilities.",
              version="0.1.0", lifespan=lifespan)
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)

origins = settings.cors_origins()
app.add_middleware(CORSMiddleware, allow_origins=origins, allow_credentials=True,
                   allow_methods=["*"], allow_headers=["*"])

app.include_router(auth.router)
app.include_router(projects.router)
app.include_router(datasets.router)
app.include_router(ingest.router)
app.include_router(runs.router)
app.include_router(targets.router)
app.include_router(validation.router)
app.include_router(reports.router)
app.include_router(sources.router)
app.include_router(admin.router)


def _health_payload() -> dict:
    return {"ok": True, "code_version": settings.CODE_VERSION,
            "postgis": False, "redis": bool(settings.REDIS_URL),
            "public_access": True, "sandbox_runs": bool(settings.PUBLIC_SANDBOX_RUNS),
            "note": "Public read-only access; writes require admin login. "
                    "SQLite + in-process jobs build. "
                    "PostGIS/Redis paths activate when configured. "
                    "On Render free tier the filesystem is ephemeral: "
                    "uploads and new runs reset on restart."}


@app.get("/health")
async def health():
    return _health_payload()


# Render Blueprint healthCheckPath is /api/health; the Vite dev proxy strips
# /api, so both paths must answer 200.
@app.get("/api/health")
async def health_aliased():
    return _health_payload()


@app.get("/")
async def root():
    return {"service": "mwamba-api", "docs": "/docs", "health": "/health"}
