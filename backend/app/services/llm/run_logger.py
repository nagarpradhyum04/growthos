"""Records every agent execution in agent_runs (observability). Writes in its own session so a
failed run is still recorded when the caller's transaction rolls back."""
import re
import uuid
from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

from app.models.enums import AgentRunStatus

_EMAIL_RE = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")


def redact(value: Any) -> Any:
    """Remove email addresses from logged payloads. Secrets are never part of agent inputs."""
    if isinstance(value, str):
        return _EMAIL_RE.sub("[email]", value)
    if isinstance(value, dict):
        return {k: redact(v) for k, v in value.items()}
    if isinstance(value, list):
        return [redact(v) for v in value]
    return value


@dataclass
class RunContext:
    organization_id: uuid.UUID | None = None
    lead_id: uuid.UUID | None = None
    campaign_id: uuid.UUID | None = None


class RunLogger(ABC):
    @abstractmethod
    def start(self, *, agent_name: str, ctx: RunContext, provider: str, model: str,
              prompt_version: str, input_data: dict) -> uuid.UUID | None: ...

    @abstractmethod
    def finish(self, run_id: uuid.UUID | None, *, status: AgentRunStatus, attempts: int,
               output: dict | None, error: str | None, latency_ms: int) -> None: ...


class NullRunLogger(RunLogger):
    """Used by the evaluation script and unit tests that don't need a database."""

    def start(self, **kwargs) -> None:
        return None

    def finish(self, run_id, **kwargs) -> None:
        return None


class DbRunLogger(RunLogger):
    def __init__(self, session_factory, log_payloads: bool = True):
        self._session_factory = session_factory
        self._log_payloads = log_payloads

    def start(self, *, agent_name, ctx, provider, model, prompt_version, input_data):
        from app.models import AgentRun

        if ctx.organization_id is None:
            return None
        run = AgentRun(
            organization_id=ctx.organization_id,
            agent_name=agent_name,
            lead_id=ctx.lead_id,
            campaign_id=ctx.campaign_id,
            provider=provider,
            model=model,
            prompt_version=prompt_version,
            status=AgentRunStatus.RUNNING,
            input=redact(input_data) if self._log_payloads else None,
            started_at=datetime.now(timezone.utc),
        )
        with self._session_factory() as db:
            db.add(run)
            db.commit()
            return run.id

    def finish(self, run_id, *, status, attempts, output, error, latency_ms):
        from app.models import AgentRun

        if run_id is None:
            return
        with self._session_factory() as db:
            run = db.get(AgentRun, run_id)
            if run is None:
                return
            run.status = status
            run.attempts = attempts
            run.output = redact(output) if (self._log_payloads and output is not None) else None
            run.error = error
            run.completed_at = datetime.now(timezone.utc)
            run.latency_ms = latency_ms
            db.commit()
