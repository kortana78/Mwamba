"""Auth dependencies + audit helper + org scoping."""
from __future__ import annotations
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from .database import get_db
from . import models
from .auth import parse_token

_bearer = HTTPBearer(auto_error=False)


async def current_user(creds: HTTPAuthorizationCredentials | None = Depends(_bearer),
                       db: AsyncSession = Depends(get_db)) -> models.User:
    # API-key path: "ApiKey <prefix>.<secret>" accepted as well as JWT
    if creds is None or not creds.credentials:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Not authenticated")
    raw = creds.credentials
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


def require_role(*roles: str):
    async def _check(user: models.User = Depends(current_user)) -> models.User:
        if user.role not in roles and user.role != "admin":
            raise HTTPException(status_code=403, detail=f"Requires role {roles}")
        return user
    return _check


async def guard_write(user: models.User = Depends(current_user)) -> models.User:
    """DEMO_MODE: viewer accounts are read-only (demo user can look, not touch).
    Admin/geologist/analyst keep write access so the demo stays manageable."""
    from .config import settings as _s
    if _s.DEMO_MODE and user.role == "viewer":
        raise HTTPException(status_code=403, detail="Demo mode: read-only account. Sign in with an editor role to make changes.")
    return user


async def audit(db: AsyncSession, user: models.User, action: str,
                entity: str, entity_id: str, detail: str = "") -> None:
    db.add(models.AuditLog(org_id=user.org_id, user_id=user.id, action=action,
                           entity=entity, entity_id=entity_id, detail=detail[:2000]))
