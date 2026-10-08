from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.deps import CurrentUser, container, current_user
from app.db import get_db
from app.models import Job
from app.models.enums import JobStatus
from app.schemas import JobOut
from app.services import analytics_service, jobs
from app.services.container import Container

router = APIRouter(prefix="/analytics", tags=["analytics"])


@router.get("")
def get_analytics(cu: CurrentUser = Depends(current_user), db: Session = Depends(get_db)):
    """Deterministic metrics computed from the database. No LLM involved."""
    return analytics_service.compute_analytics(db, cu.org_id)


@router.post("/insights")
def generate_insights(cu: CurrentUser = Depends(current_user), db: Session = Depends(get_db),
                      c: Container = Depends(container)):
    """Run the Analytics Agent now (synchronously) on the current metrics."""
    return analytics_service.generate_insights(db, cu.org_id, c)


@router.post("/insights/queue", response_model=JobOut, status_code=202)
def queue_insights(cu: CurrentUser = Depends(current_user), db: Session = Depends(get_db)):
    job = jobs.enqueue(db, "generate_insights", {}, organization_id=cu.org_id, dedupe_key=f"insights:{cu.org_id}")
    db.commit()
    return job


@router.get("/insights/latest")
def latest_insights(cu: CurrentUser = Depends(current_user), db: Session = Depends(get_db)):
    job = db.scalar(select(Job).where(Job.organization_id == cu.org_id, Job.job_type == "generate_insights",
                                      Job.status == JobStatus.SUCCEEDED).order_by(Job.updated_at.desc()))
    return {"generated_at": job.updated_at if job else None, "result": job.result if job else None}
