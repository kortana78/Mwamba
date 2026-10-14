"""Job launcher: Celery when REDIS_URL is set, else FastAPI BackgroundTasks (in-process)."""
from __future__ import annotations
import os
from .config import settings


def launch_run(run_id: str, background=None) -> dict:
    """Enqueue run_analysis_sync(run_id). Returns {'queued': True, 'via': ...}."""
    db_url = os.environ.get("MWAMBA_DB_URL", settings.MWAMBA_DB_URL)
    storage_dir = os.environ.get("MWAMBA_STORAGE_DIR", settings.MWAMBA_STORAGE_DIR)
    redis_url = os.environ.get("REDIS_URL", settings.REDIS_URL)
    if redis_url:
        try:
            from celery import Celery
            app = Celery("mwamba", broker=redis_url)
            app.send_task("mwamba.run_analysis", args=[run_id, db_url, storage_dir])
            return {"queued": True, "via": "celery"}
        except Exception:
            pass
    if background is not None:
        from .services.prospectivity import run_analysis_sync
        background.add_task(run_analysis_sync, run_id, db_url, storage_dir)
        return {"queued": True, "via": "background-tasks"}
    # synchronous fallback (tests)
    from .services.prospectivity import run_analysis_sync
    return run_analysis_sync(run_id, db_url, storage_dir)
