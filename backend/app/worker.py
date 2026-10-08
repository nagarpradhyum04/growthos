"""Background worker: `python -m app.worker`.

Loop: recover stale jobs -> process due follow-ups -> run queued jobs -> sleep.
"""
import logging
import signal
import time

from sqlalchemy import select

from app.config import get_settings
from app.db import SessionLocal
from app.logging_config import configure_logging
from app.services import jobs
from app.services.container import get_container
from app.services.followup_service import process_due_followups
from app.workers.handlers import HANDLERS

logger = logging.getLogger("growthos.worker")
_running = True


def _stop(*_):
    global _running
    _running = False
    logger.info("Shutting down after current job...")


def run_once(max_jobs: int = 20) -> dict:
    """One worker tick. Also used by tests."""
    stats = {"jobs": 0, "followups": {}}
    with SessionLocal() as db:
        jobs.requeue_stale(db)
        try:
            stats["followups"] = process_due_followups(db, get_container())
        except Exception:  # noqa: BLE001
            db.rollback()
            logger.exception("Follow-up processing failed")
        try:
            from app.models import Organization
            from app.services.lifecycle_service import process_lifecycle

            for org_id in db.scalars(select(Organization.id)).all():
                out = process_lifecycle(db, get_container(), org_id)
                if out["sent"]:
                    stats.setdefault("lifecycle", {})[str(org_id)] = out
        except Exception:  # noqa: BLE001
            db.rollback()
            logger.exception("Lifecycle processing failed")
        for _ in range(max_jobs):
            job = jobs.claim_next(db)
            if job is None:
                break
            jobs.execute(db, job, HANDLERS)
            stats["jobs"] += 1
    return stats


def main() -> None:
    configure_logging()
    signal.signal(signal.SIGINT, _stop)
    signal.signal(signal.SIGTERM, _stop)
    poll = get_settings().worker_poll_seconds
    logger.info("GrowthOS worker started (poll every %.0fs)", poll)
    while _running:
        stats = run_once()
        if stats["jobs"] or stats["followups"]:
            logger.info("tick: %s", stats)
        time.sleep(poll)


if __name__ == "__main__":
    main()
