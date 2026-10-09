"""Background job handlers. Each receives a session and the job; returns a JSON-able result."""
import uuid

from sqlalchemy.orm import Session

from app.models import EmailReply, Job, Lead
from app.models.enums import EmailStatus
from app.services import analytics_service, reply_service
from app.services.common import get_owned
from app.services.container import get_container
from app.services.email_service import send_email
from app.services.orchestrator import Orchestrator


def process_lead(db: Session, job: Job) -> dict:
    lead = get_owned(db, Lead, uuid.UUID(job.payload["lead_id"]), job.organization_id)
    return Orchestrator(db, get_container()).process_lead(lead).to_dict()


def analyze_reply(db: Session, job: Job) -> dict:
    reply = get_owned(db, EmailReply, uuid.UUID(job.payload["reply_id"]), job.organization_id)
    reply = reply_service.analyze_reply(db, reply, get_container())
    return {"classification": reply.classification.value if reply.classification else None}


def send_scheduled_email(db: Session, job: Job) -> dict:
    from app.models import Email

    email = get_owned(db, Email, uuid.UUID(job.payload["email_id"]), job.organization_id)
    if email.status != EmailStatus.SCHEDULED:
        return {"skipped": f"email is {email.status.value}"}
    email = send_email(db, email.id, job.organization_id, get_container())
    return {"status": email.status.value}


def generate_insights(db: Session, job: Job) -> dict:
    return analytics_service.generate_insights(db, job.organization_id, get_container())


def run_goal(db: Session, job: Job) -> dict:
    from app.models import Workflow

    wf = get_owned(db, Workflow, uuid.UUID(job.payload["workflow_id"]), job.organization_id)
    return Orchestrator(db, get_container()).run_command(wf, int(job.payload.get("max_leads", 25)))


HANDLERS = {
    "run_goal": run_goal,
    "process_lead": process_lead,
    "analyze_reply": analyze_reply,
    "send_scheduled_email": send_scheduled_email,
    "generate_insights": generate_insights,
}
