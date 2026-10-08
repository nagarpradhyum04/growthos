"""Orchestrator: decides which agent runs next for a lead and passes structured data between them.

It never sends email — sending only happens through email_service.send_email (can_send gate).
It skips steps whose results already exist, so re-running is cheap and idempotent.
"""
from dataclasses import asdict, dataclass, field

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.errors import GrowthOSError
from app.models import Email, Lead
from app.models.enums import LeadStatus
from app.services import lead_service
from app.services.common import latest_research
from app.services.container import Container


@dataclass
class StepResult:
    step: str
    status: str  # done | skipped | stopped | failed
    detail: str = ""


@dataclass
class WorkflowResult:
    lead_id: str
    steps: list[StepResult] = field(default_factory=list)
    lead_status: str = ""
    email_id: str | None = None

    def to_dict(self) -> dict:
        return asdict(self)


class Orchestrator:
    def __init__(self, db: Session, container: Container):
        self.db = db
        self.container = container

    def process_lead(self, lead: Lead, *, force: bool = False) -> WorkflowResult:
        """Lead -> Research -> Qualification -> Draft email (awaiting human review)."""
        result = WorkflowResult(lead_id=str(lead.id))

        def finish() -> WorkflowResult:
            result.lead_status = lead.status.value
            return result

        if lead.status == LeadStatus.SUPPRESSED or lead.disabled:
            result.steps.append(StepResult("guard", "stopped", "Lead is suppressed or disabled"))
            return finish()

        # 1. Research
        if latest_research(self.db, lead.id) is None or force:
            if not self._run(result, "research", lambda: lead_service.research_lead(self.db, lead, self.container)):
                return finish()
        else:
            result.steps.append(StepResult("research", "skipped", "Research already exists"))

        # 2. Qualification
        if lead.qualified is None or force:
            if not self._run(result, "qualification", lambda: lead_service.qualify_lead(self.db, lead, self.container)):
                return finish()
        else:
            result.steps.append(StepResult("qualification", "skipped", "Already qualified"))
        if not lead.qualified:
            result.steps.append(StepResult("outreach", "stopped", f"Not qualified (score {lead.qualification_score})"))
            return finish()

        # 3. Outreach draft
        existing = self.db.scalar(select(Email).where(Email.lead_id == lead.id, Email.sequence_number == 0))
        if existing is None:
            if not self._run(result, "outreach", lambda: lead_service.generate_initial_email(self.db, lead, self.container)):
                return finish()
            existing = self.db.scalar(select(Email).where(Email.lead_id == lead.id, Email.sequence_number == 0))
        else:
            result.steps.append(StepResult("outreach", "skipped", "Initial email already exists"))
        result.email_id = str(existing.id) if existing else None
        return finish()

    def _run(self, result: WorkflowResult, step: str, fn) -> bool:
        try:
            fn()
            self.db.commit()  # persist each step so partial progress survives a later failure
            result.steps.append(StepResult(step, "done"))
            return True
        except GrowthOSError as exc:
            self.db.rollback()
            result.steps.append(StepResult(step, "failed", exc.message))
            return False
