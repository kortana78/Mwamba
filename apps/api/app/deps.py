"""Auth dependencies + audit helper + visibility helpers.

Access model: anyone may READ public projects/datasets/runs/targets without
logging in. Every write (POST/PUT/PATCH/DELETE) requires an admin JWT.
Viewer/analyst/geologist roles are kept in the schema but dormant: only
role == "admin" may write.
"""
from __future__ import annotations
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from .database import get_db
from . import models
from .auth import parse_token

_bearer = HTTPBearer(auto_error=False)


async def optional_user(creds: HTTPAuthorizationCredentials | None = Depends(_bearer),
                        db: AsyncSession = Depends(get_db)) -> models.User | None:
    """Public endpoints: return the user when a valid token/API key is given,
    else None (never 401 — reads are open)."""
    if creds is None or not creds.credentials:
        return None
    try:
        return await _resolve(creds.credentials, db)
    except HTTPException:
        return None


async def _resolve(raw: str, db: AsyncSession) -> models.User:
    if raw.startswith("mw_"):
        import hashlib
        try:
            prefix, secret = raw.split(".", 1)
        except ValueError:
            raise HTTPException(status_code=401, detail="Malformed API key")
        h = hashlib.sha256(secret.encode()).hexdigest()
        res = await db.execute(select(models.ApiKey).where(models.ApiKey.prefix == prefix,
                                                           models.ApiKey.key_hash == h))
        key = res.scalar_one_or_none()
        if key is None:
            raise HTTPException(status_code=401, detail="Invalid API key")
        res = await db.execute(select(models.User).where(models.User.id == key.user_id))
        user = res.scalar_one_or_none()
        if user is None:
            raise HTTPException(status_code=401, detail="API key owner gone")
        return user
    uid = parse_token(raw)
    if uid is None:
        raise HTTPException(status_code=401, detail="Invalid or expired token")
    res = await db.execute(select(models.User).where(models.User.id == uid))
    user = res.scalar_one_or_none()
    if user is None:
        raise HTTPException(status_code=401, detail="User not found")
    return user


async def current_user(creds: HTTPAuthorizationCredentials | None = Depends(_bearer),
                       db: AsyncSession = Depends(get_db)) -> models.User:
    # API-key path: "ApiKey <prefix>.<secret>" accepted as well as JWT
    if creds is None or not creds.credentials:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Not authenticated")
    return await _resolve(creds.credentials, db)


async def require_admin(user: models.User = Depends(current_user)) -> models.User:
    """Every write path depends on this. Non-admin roles are dormant."""
    if user.role != "admin":
        raise HTTPException(status_code=403, detail="Admin only")
    return user


def require_role(*roles: str):
    async def _check(user: models.User = Depends(current_user)) -> models.User:
        if user.role not in roles and user.role != "admin":
            raise HTTPException(status_code=403, detail=f"Requires role {roles}")
        return user
    return _check


async def is_admin(user: models.User | None) -> bool:
    return user is not None and user.role == "admin"


def can_read_private(user: models.User | None, org_id: str) -> bool:
    """Private rows are visible only to an admin of the same org."""
    return user is not None and user.role == "admin" and user.org_id == org_id


def visible_project(p, user: models.User | None) -> bool:
    if (p.visibility or "private") == "public":
        return True
    return can_read_private(user, p.org_id)


def dataset_is_restricted(d) -> bool:
    return bool((d.provenance or {}).get("restricted"))


def visible_dataset(d, user: models.User | None) -> bool:
    """Restricted (no-redistribution) datasets are never publicly visible,
    even if mislabelled — raw data stays admin-only."""
    if dataset_is_restricted(d):
        return can_read_private(user, d.org_id)
    if (d.visibility or "private") == "public":
        return True
    return can_read_private(user, d.org_id)


async def audit(db: AsyncSession, user: models.User, action: str,
                entity: str, entity_id: str, detail: str = "") -> None:
    db.add(models.AuditLog(org_id=user.org_id, user_id=user.id, action=action,
                           entity=entity, entity_id=entity_id, detail=detail[:2000]))
