from __future__ import annotations
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from ..database import get_db
from .. import models, schemas
from ..auth import verify_password, make_token
from ..deps import current_user

router = APIRouter(prefix="/auth", tags=["auth"])


@router.post("/login", response_model=schemas.TokenOut)
async def login(body: schemas.LoginIn, db: AsyncSession = Depends(get_db)):
    res = await db.execute(select(models.User).where(models.User.email == body.email.lower()))
    user = res.scalar_one_or_none()
    if user is None or not verify_password(body.password, user.password_hash):
        raise HTTPException(401, "Invalid email or password")
    return {"access_token": make_token(user.id), "token_type": "bearer"}


@router.get("/me", response_model=schemas.UserOut)
async def me(user: models.User = Depends(current_user)):
    return {"id": user.id, "email": user.email, "role": user.role, "org_id": user.org_id}
