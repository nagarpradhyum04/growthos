"""LLMService: structured output validation, correction retry, transient retries, run logging."""
import pytest
from sqlalchemy import select

from app.errors import AgentFailedError
from app.models import AgentRun, Organization
from app.models.enums import AgentRunStatus
from app.services.agents.schemas import ReplyAnalysisOutput
from app.services.llm.provider import LLMProviderError, LLMRateLimitError, LLMTimeoutError
from app.services.llm.run_logger import DbRunLogger, RunContext, redact
from app.services.llm.service import LLMService
from app.db import SessionLocal
from tests.fakes import ScriptedProvider

VALID = {"classification": "INTERESTED", "summary": "Wants a call.", "recommended_action": "Book it.",
         "requires_human_attention": True}


def _service(provider, logger=None) -> LLMService:
    return LLMService(provider, "test-model", run_logger=logger, max_transient_retries=2, backoff_seconds=0)


def _run(service, ctx=None, validator=None):
    return service.run_structured(agent_name="reply_analysis", prompt_name="reply_analysis",
                                  input_data={"reply": {"body": "hi"}}, output_schema=ReplyAnalysisOutput,
                                  ctx=ctx, validator=validator)


def test_valid_output_is_parsed():
    result = _run(_service(ScriptedProvider(VALID)))
    assert result.output.classification == "INTERESTED"
    assert result.attempts == 1
    assert result.prompt_version == "reply_analysis_v2"


def test_system_prompt_contains_versioned_prompt_and_schema():
    provider = ScriptedProvider(VALID)
    _run(_service(provider))
    system = provider.requests[0].system_prompt
    assert "Reply Analysis Agent" in system and '"classification"' in system


def test_markdown_code_fence_is_tolerated():
    import json

    result = _run(_service(ScriptedProvider("```json\n" + json.dumps(VALID) + "\n```")))
    assert result.output.summary == "Wants a call."


def test_invalid_output_retries_once_with_correction():
    provider = ScriptedProvider({"classification": "MAYBE"}, VALID)
    result = _run(_service(provider))
    assert result.attempts == 2
    correction = provider.requests[1].messages[-1].content
    assert "previous response was invalid" in correction and "classification" in correction


def test_invalid_output_twice_fails_loudly():
    with pytest.raises(AgentFailedError):
        _run(_service(ScriptedProvider("not json at all", {"summary": "still wrong"})))


def test_business_validator_triggers_correction():
    calls = []

    def validator(out):
        calls.append(out)
        return ["summary must mention pricing"] if len(calls) == 1 else []

    provider = ScriptedProvider(VALID, VALID)
    assert _run(_service(provider), validator=validator).attempts == 2
    assert "summary must mention pricing" in provider.requests[1].messages[-1].content


def test_transient_errors_are_retried():
    provider = ScriptedProvider(LLMTimeoutError("t"), LLMRateLimitError("r"), VALID)
    assert _run(_service(provider)).output.classification == "INTERESTED"
    assert len(provider.requests) == 3


def test_transient_errors_exhausted_fail():
    provider = ScriptedProvider(LLMTimeoutError("t"), LLMTimeoutError("t"), LLMTimeoutError("t"))
    with pytest.raises(AgentFailedError):
        _run(_service(provider))


def test_non_retryable_error_fails_immediately():
    provider = ScriptedProvider(LLMProviderError("bad key"), VALID)
    with pytest.raises(AgentFailedError):
        _run(_service(provider))
    assert len(provider.requests) == 1


def _org(db) -> Organization:
    org = Organization(name="Org")
    db.add(org)
    db.commit()
    return org


def test_runs_are_logged_with_metadata(db):
    org = _org(db)
    service = _service(ScriptedProvider(VALID), DbRunLogger(SessionLocal))
    _run(service, ctx=RunContext(organization_id=org.id))
    run = db.scalar(select(AgentRun))
    assert run.status == AgentRunStatus.SUCCEEDED
    assert run.agent_name == "reply_analysis" and run.prompt_version == "reply_analysis_v2"
    assert run.model == "test-model" and run.provider == "scripted"
    assert run.latency_ms is not None and run.completed_at is not None
    assert run.output["classification"] == "INTERESTED"


def test_failed_runs_are_logged(db):
    org = _org(db)
    service = _service(ScriptedProvider("garbage", "garbage"), DbRunLogger(SessionLocal))
    with pytest.raises(AgentFailedError):
        _run(service, ctx=RunContext(organization_id=org.id, lead_id=None))
    run = db.scalar(select(AgentRun))
    assert run.status == AgentRunStatus.FAILED and run.attempts == 2
    assert "Invalid LLM output" in run.error


def test_logged_payloads_are_redacted():
    assert redact({"a": ["write to jane@acme.com now"]}) == {"a": ["write to [email] now"]}


def test_unknown_org_context_does_not_log(db):
    service = _service(ScriptedProvider(VALID), DbRunLogger(SessionLocal))
    _run(service, ctx=RunContext(organization_id=None))
    assert db.scalar(select(AgentRun)) is None
