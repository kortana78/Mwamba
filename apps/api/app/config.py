"""Central configuration — secrets via environment only."""
from __future__ import annotations
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    MWAMBA_SECRET_KEY: str = "dev-secret-change-me-please-32chars!!"
    # Render Blueprint uses JWT_SECRET (generateValue) — accepted as alias.
    JWT_SECRET: str = ""
    MWAMBA_DB_URL: str = "sqlite+aiosqlite:///./storage/mwamba.db"
    # Render Postgres later: DATABASE_URL (sync URL or postgres://) accepted as alias.
    DATABASE_URL: str = ""
    MWAMBA_STORAGE_DIR: str = "./storage"
    MWAMBA_CORS_ORIGINS: str = "http://localhost:5173,http://127.0.0.1:5173"
    # Render static site origin, e.g. https://mwamba-web.onrender.com
    FRONTEND_ORIGIN: str = ""
    # Admin account — created from these on first start. There is deliberately
    # NO default password in code: set both in production. For local dev with
    # neither set, a random password is generated once and printed to the logs.
    ADMIN_EMAIL: str = ""
    ADMIN_PASSWORD: str = ""
    # Public access model: reads are open; writes need the admin account.
    # Optional sandbox: the public may run (ephemeral, unsaved, rate-limited)
    # analyses on demo projects only.
    PUBLIC_SANDBOX_RUNS: bool = False
    PUBLIC_RATE_PER_MIN: int = 60
    SANDBOX_PER_HOUR: int = 5
    REDIS_URL: str = ""
    LLM_EXTRACTION_ENABLED: bool = False
    OPENAI_API_KEY: str = ""
    MINDAT_API_KEY: str = ""
    MWAMBA_MAX_UPLOAD_MB: int = 100
    MAX_UPLOAD_MB: int = 0  # alias; when >0 overrides MWAMBA_MAX_UPLOAD_MB
    MWAMBA_MAX_GRID_CELLS: int = 2_500_000
    MWAMBA_RUN_TIMEOUT_S: int = 240
    CODE_VERSION: str = "0.1.0"

    def secret_key(self) -> str:
        return self.JWT_SECRET or self.MWAMBA_SECRET_KEY

    def db_url(self) -> str:
        if self.DATABASE_URL:
            u = self.DATABASE_URL
            # asyncpg driver for SQLAlchemy async; keep sqlite URLs untouched
            if u.startswith("postgres://"):
                u = u.replace("postgres://", "postgresql+asyncpg://", 1)
            elif u.startswith("postgresql://"):
                u = u.replace("postgresql://", "postgresql+asyncpg://", 1)
            return u
        return self.MWAMBA_DB_URL

    def storage_dir(self) -> str:
        import os as _os
        return _os.environ.get("MWAMBA_STORAGE_DIR", self.MWAMBA_STORAGE_DIR)

    def cors_origins(self) -> list[str]:
        base = [o.strip() for o in self.MWAMBA_CORS_ORIGINS.split(",") if o.strip()]
        if self.FRONTEND_ORIGIN.strip() and self.FRONTEND_ORIGIN.strip() not in base:
            base.append(self.FRONTEND_ORIGIN.strip())
        return base

    def max_upload_mb(self) -> int:
        return self.MAX_UPLOAD_MB or self.MWAMBA_MAX_UPLOAD_MB

    def admin_email(self) -> str:
        return (self.ADMIN_EMAIL or "admin@mwamba.local").lower()

    def admin_password_or_generate(self) -> tuple[str, bool]:
        """(password, was_generated). No default password lives in code."""
        if self.ADMIN_PASSWORD:
            return self.ADMIN_PASSWORD, False
        import secrets as _secrets
        return _secrets.token_urlsafe(24), True


settings = Settings()
