"""Background worker: `python -m app.worker`.

Loop: recover stale jobs -> process due follow-ups -> run queued jobs -> sleep.
"""
import logging
import signal
import threading
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
_last_inbox_poll = 0.0


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
        try:
            from app.services.social_service import schedule_weekly

            if get_settings().social_auto_weekly and (queued := schedule_weekly(db)):
                stats["social_weeks_queued"] = queued
        except Exception:  # noqa: BLE001
            db.rollback()
            logger.exception("Weekly social scheduling failed")
        global _last_inbox_poll
        settings = get_settings()
        if settings.imap_host and time.monotonic() - _last_inbox_poll >= settings.imap_poll_seconds:
            _last_inbox_poll = time.monotonic()
            from app.services.email.imap_inbox import poll_inbox

            inbox = poll_inbox(db, settings)
            if inbox.get("recorded") or inbox.get("error"):
                stats["inbox"] = inbox
        for _ in range(max_jobs):
            job = jobs.claim_next(db)
            if job is None:
                break
            jobs.execute(db, job, HANDLERS)
            stats["jobs"] += 1
    return stats


def _job_loop(index: int, poll: float) -> None:
    """Extra job runners so a long command (e.g. a big prospect run) doesn't block other commands.
    Jobs are claimed with SELECT ... FOR UPDATE SKIP LOCKED, so runners never take the same job."""
    while _running:
        ran = 0
        with SessionLocal() as db:
            for _ in range(20):
                job = jobs.claim_next(db)
                if job is None:
                    break
                jobs.execute(db, job, HANDLERS)
                ran += 1
        if not ran:
            time.sleep(poll)


def main() -> None:
    configure_logging()
    signal.signal(signal.SIGINT, _stop)
    signal.signal(signal.SIGTERM, _stop)
    settings = get_settings()
    poll = settings.worker_poll_seconds
    extra = max(0, settings.worker_concurrency - 1)
    for i in range(extra):
        threading.Thread(target=_job_loop, args=(i + 1, poll), daemon=True, name=f"job-runner-{i + 1}").start()
    logger.info("GrowthOS worker started (poll every %.0fs, %d job runner(s))", poll, extra + 1)
    while _running:
        stats = run_once()
        if stats["jobs"] or stats["followups"]:
            logger.info("tick: %s", stats)
        time.sleep(poll)


if __name__ == "__main__":
    main()
