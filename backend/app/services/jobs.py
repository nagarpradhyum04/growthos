"""Minimal PostgreSQL-backed job queue (no extra infrastructure).

API code enqueues jobs; `python -m app.worker` claims them with SELECT ... FOR UPDATE SKIP LOCKED.
"""
import logging
import uuid
from collections.abc import Callable
from datetime import datetime, timedelta, timezone

from sqlalchemy import select, update
from sqlalchemy.orm import Session

from app.errors import AgentFailedError, ExternalServiceError, GrowthOSError
from app.models import Job
from app.models.enums import JobStatus

logger = logging.getLogger(__name__)

STALE_AFTER = timedelta(minutes=10)
# Errors worth retrying later; anything else (invalid state, blocked send...) fails immediately.
RETRYABLE_ERRORS = (AgentFailedError, ExternalServiceError)


def enqueue(db: Session, job_type: str, payload: dict, *, organization_id: uuid.UUID | None,
            dedupe_key: str | None = None, run_at: datetime | None = None, max_attempts: int = 3) -> Job:
    if dedupe_key:
        existing = db.scalar(select(Job).where(Job.dedupe_key == dedupe_key,
                                               Job.status.in_([JobStatus.QUEUED, JobStatus.RUNNING])))
        if existing:
            return existing
    job = Job(organization_id=organization_id, job_type=job_type, payload=payload, dedupe_key=dedupe_key,
              run_at=run_at or datetime.now(timezone.utc), max_attempts=max_attempts)
    db.add(job)
    db.flush()
    return job


def claim_next(db: Session) -> Job | None:
    job = db.scalar(
        select(Job)
        .where(Job.status == JobStatus.QUEUED, Job.run_at <= datetime.now(timezone.utc))
        .order_by(Job.run_at)
        .limit(1)
        .with_for_update(skip_locked=True)
    )
    if job is None:
        return None
    job.status = JobStatus.RUNNING
    job.attempts += 1
    db.commit()
    return job


def requeue_stale(db: Session) -> int:
    """Recover jobs left RUNNING by a crashed worker."""
    result = db.execute(
        update(Job)
        .where(Job.status == JobStatus.RUNNING, Job.updated_at < datetime.now(timezone.utc) - STALE_AFTER)
        .values(status=JobStatus.QUEUED)
    )
    db.commit()
    return result.rowcount or 0


def execute(db: Session, job: Job, handlers: dict[str, Callable[[Session, Job], dict | None]]) -> None:
    handler = handlers.get(job.job_type)
    try:
        if handler is None:
            raise GrowthOSError(f"No handler for job type '{job.job_type}'")
        result = handler(db, job)
        db.commit()
        job = db.get(Job, job.id)
        job.status = JobStatus.SUCCEEDED
        job.result = result
        job.last_error = None
        db.commit()
    except Exception as exc:  # noqa: BLE001 — the worker must survive any job failure
        db.rollback()
        job = db.get(Job, job.id)
        message = exc.message if isinstance(exc, GrowthOSError) else f"{type(exc).__name__}"
        retryable = isinstance(exc, RETRYABLE_ERRORS) or not isinstance(exc, GrowthOSError)
        if retryable and job.attempts < job.max_attempts:
            job.status = JobStatus.QUEUED
            job.run_at = datetime.now(timezone.utc) + timedelta(seconds=30 * 2**job.attempts)
        else:
            job.status = JobStatus.FAILED
        job.last_error = message[:2000]
        db.commit()
        if isinstance(exc, GrowthOSError):
            logger.warning("Job %s (%s) failed: %s", job.id, job.job_type, message)
        else:
            logger.exception("Job %s (%s) crashed", job.id, job.job_type)
