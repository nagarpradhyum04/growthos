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


def test_gemini_llm_provider_requests_json_and_parses_text():
    import json as _json

    import httpx

    from app.services.llm.gemini_provider import GeminiLLMProvider
    from app.services.llm.provider import LLMMessage, LLMRateLimitError, LLMRequest

    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["url"], seen["body"] = str(request.url), _json.loads(request.content)
        return httpx.Response(200, json={"candidates": [{"content": {"parts": [{"text": '{"ok": true}'}]}}],
                                         "usageMetadata": {"promptTokenCount": 7, "candidatesTokenCount": 3}})

    p = GeminiLLMProvider("k", 10, transport=httpx.MockTransport(handler))
    out = p.complete_json(LLMRequest(agent_name="x", system_prompt="sys", model="gemini-2.5-flash",
                                     messages=[LLMMessage("user", "hi")]))
    assert out.content == '{"ok": true}' and out.usage == {"prompt_tokens": 7, "completion_tokens": 3}
    assert seen["url"].endswith("models/gemini-2.5-flash:generateContent")
    assert seen["body"]["generationConfig"]["responseMimeType"] == "application/json"
    assert seen["body"]["systemInstruction"]["parts"][0]["text"] == "sys"

    limited = GeminiLLMProvider("k", 10, transport=httpx.MockTransport(lambda r: httpx.Response(429, json={})))
    try:
        limited.complete_json(LLMRequest(agent_name="x", system_prompt="s", model="m", messages=[]))
        raise AssertionError("expected rate limit")
    except LLMRateLimitError:
        pass


def test_gemini_backend_is_chosen_from_the_key():
    from app.config import Settings

    assert Settings(gemini_api_key="AIzaSyExample").resolved_gemini_backend == "ai_studio"
    vertex = Settings(gemini_api_key="AQ.Ab8Example")
    assert vertex.resolved_gemini_backend == "vertex"
    assert vertex.gemini_base_url == "https://aiplatform.googleapis.com/v1/publishers/google"
    assert Settings(gemini_api_key="AQ.x", gemini_backend="ai_studio").resolved_gemini_backend == "ai_studio"


def test_vertex_veo_polls_fetch_predict_operation_and_decodes_bytes():
    import base64

    import httpx

    from app.config import get_settings
    from app.services.media.gemini import GeminiMediaProvider

    paths = []

    def handler(request: httpx.Request) -> httpx.Response:
        paths.append(request.url.path)
        if request.url.path.endswith(":predictLongRunning"):
            return httpx.Response(200, json={"name": "projects/p/operations/op1", "done": False})
        return httpx.Response(200, json={"done": True, "response": {"videos": [
            {"bytesBase64Encoded": base64.b64encode(b"MP4").decode(), "mimeType": "video/mp4"}]}})

    s = get_settings().model_copy(update={"gemini_api_key": "AQ.test", "gemini_backend": "auto"})
    res = GeminiMediaProvider(s, transport=httpx.MockTransport(handler), poll_seconds=0).generate_video(
        "Scene 1", aspect_ratio="9:16", brand={})
    assert res.data == b"MP4" and paths[0].startswith("/v1/publishers/google/models/")
    assert paths[1].endswith(":fetchPredictOperation")


def test_json_inside_prose_and_single_item_lists_are_accepted():
    from pydantic import BaseModel

    from app.services.llm.service import _parse_and_validate

    class Out(BaseModel):
        ok: bool

    assert _parse_and_validate('Sure! Here it is:\n{"ok": true}\nHope this helps.', Out, None).ok is True
    assert _parse_and_validate('[{"ok": true}]', Out, None).ok is True


def test_gemini_skips_thought_parts_and_reports_blocked_answers():
    import httpx

    from app.services.llm.gemini_provider import GeminiLLMProvider
    from app.services.llm.provider import LLMProviderError, LLMRequest

    def ok(r):
        return httpx.Response(200, json={"candidates": [{"finishReason": "STOP", "content": {"parts": [
            {"text": "thinking...", "thought": True}, {"text": '{"ok": true}'}]}}]})

    req = LLMRequest(agent_name="x", system_prompt="s", model="m", messages=[])
    assert GeminiLLMProvider("k", 5, transport=httpx.MockTransport(ok)).complete_json(req).content == '{"ok": true}'
    blocked = GeminiLLMProvider("k", 5, transport=httpx.MockTransport(lambda r: httpx.Response(200, json={
        "candidates": [{"finishReason": "SAFETY", "content": {"parts": []}}]})))
    try:
        blocked.complete_json(req)
        raise AssertionError("expected error")
    except LLMProviderError as exc:
        assert "SAFETY" in str(exc)
