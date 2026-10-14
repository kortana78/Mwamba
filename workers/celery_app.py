"""Celery worker (activates when REDIS_URL is set; otherwise the API runs the
same function in-process via BackgroundTasks). Same signature both paths."""
from __future__ import annotations
import os

try:
    from celery import Celery

    celery_app = Celery("mwamba", broker=os.environ.get("REDIS_URL", "redis://localhost:6379/0"))

    @celery_app.task(name="mwamba.run_analysis")
    def run_analysis_task(run_id: str, db_url: str, storage_dir: str) -> dict:
        from apps.api.app.services.prospectivity import run_analysis_sync
        return run_analysis_sync(run_id, db_url, storage_dir)

except ImportError:  # celery not installed — in-process path only
    celery_app = None

    def run_analysis_task(run_id: str, db_url: str, storage_dir: str) -> dict:
        from apps.api.app.services.prospectivity import run_analysis_sync
        return run_analysis_sync(run_id, db_url, storage_dir)
