"""Shared rate limiter. Public read endpoints: 60 req/min per IP.
Sandbox runs: 5 per hour per IP (plus an in-memory per-IP log in runs.py).
Writes require admin JWT and are not rate-limited here."""
from __future__ import annotations
from slowapi import Limiter
from slowapi.util import get_remote_address

limiter = Limiter(key_func=get_remote_address)

from .config import settings as _settings  # noqa: E402

public_limit = limiter.limit(f"{int(_settings.PUBLIC_RATE_PER_MIN)}/minute")
sandbox_limit = limiter.limit(f"{int(_settings.SANDBOX_PER_HOUR)}/hour")
