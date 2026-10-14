from __future__ import annotations
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from ..database import get_db
from .. import models, schemas
from ..auth import hash_password, verify_password, make_token
from ..deps import current_user, audit

router = APIRouter(prefix="/auth", tags=["auth"])


@router.post("/register", response_model=schemas.TokenOut)
async def register(body: schemas.RegisterIn, db: AsyncSession = Depends(get_db)):
    res = await db.execute(select(models.User).where(models.User.email == body.email.lower()))
    if res.scalar_one_or_none():
        raise HTTPException(400, "Email already registered")
    org = models.Organisation(name=body.org_name)
    db.add(org)
    await db.flush()
    role = body.role if body.role in ("admin", "geologist", "analyst", "viewer") else "viewer"
    user = models.User(email=body.email.lower(), password_hash=hash_password(body.password),
                       role=role, org_id=org.id)
    db.add(user)
    await db.flush()
    await audit(db, user, "register", "user", user.id, f"org={org.name}")
    await db.commit()
    return {"access_token": make_token(user.id), "token_type": "bearer"}


@router.post("/login", response_model=schemas.TokenOut)
async def login(body: schemas.LoginIn, db: AsyncSession = Depends(get_db)):
    res = await db.execute(select(models.User).where(models.User.email == body.email.lower()))
    user = res.scalar_one_or_none()
    if user is None or not verify_password(body.password, user.password_hash):
        raise HTTPException(401, "Invalid email or password")
    return {"access_token": make_token(user.id), "token_type": "bearer"}


@router.get("/demo-config")
async def demo_config():
    """Frontend asks whether to show the one-click 'Try the demo' button.
    No secret is ever sent to the browser — the button calls POST /auth/demo,
    which mints a token server-side when DEMO_MODE is on."""
    from ..config import settings as _s
    return {"demo_mode": bool(_s.DEMO_MODE)}


@router.post("/demo", response_model=schemas.TokenOut)
async def demo_login(db: AsyncSession = Depends(get_db)):
    """One-click demo login (DEMO_MODE only). No password travels to the
    browser and none is shown on screen — the server mints a token for the
    read-mostly demo account (analyst role: can run, cannot reach Admin)."""
    from ..config import settings as _s
    if not _s.DEMO_MODE:
        raise HTTPException(404, "Demo mode is off")
    res = await db.execute(select(models.User).where(models.User.email == _s.demo_email()))
    user = res.scalar_one_or_none()
    if user is None:
        raise HTTPException(503, "Demo account not seeded yet — retry in a few seconds")
    await audit(db, user, "demo.login", "user", user.id, "one-click demo")
    await db.commit()
    return {"access_token": make_token(user.id), "token_type": "bearer"}


@router.get("/me", response_model=schemas.UserOut)
async def me(user: models.User = Depends(current_user)):
    return {"id": user.id, "email": user.email, "role": user.role, "org_id": user.org_id}
