"""Auth: bcrypt hashing + JWT. Roles: admin/geologist/analyst/viewer."""
from __future__ import annotations
import datetime as dt
from jose import jwt
import bcrypt as _bcrypt
from .config import settings

ALGORITHM = "HS256"
TOKEN_HOURS = 24


def hash_password(pw: str) -> str:
    raw = pw.encode("utf-8")[:72]
    return _bcrypt.hashpw(raw, _bcrypt.gensalt()).decode("ascii")


def verify_password(pw: str, hashed: str) -> bool:
    try:
        return _bcrypt.checkpw(pw.encode("utf-8")[:72], hashed.encode("ascii"))
    except Exception:
        return False


def make_token(user_id: str) -> str:
    exp = dt.datetime.now(dt.timezone.utc) + dt.timedelta(hours=TOKEN_HOURS)
    return jwt.encode({"sub": user_id, "exp": exp}, settings.secret_key(), algorithm=ALGORITHM)


def parse_token(token: str) -> str | None:
    try:
        payload = jwt.decode(token, settings.secret_key(), algorithms=[ALGORITHM])
        return str(payload.get("sub"))
    except Exception:
        return None
