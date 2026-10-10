"""LLMService: the single entry point agents use to call the LLM.

Responsibilities:
- build the request from a versioned prompt + structured input + output JSON schema
- retry transient provider errors (timeout / rate limit) with backoff
- validate output against a Pydantic schema (+ optional business validator)
- on invalid output, retry ONCE with a correction request, then fail loudly
- record every run in agent_runs
"""
import json
import logging
import time
from collections.abc import Callable
from dataclasses import dataclass
from typing import Generic, TypeVar

from pydantic import BaseModel, ValidationError

from app.config import Settings, get_settings
from app.errors import AgentFailedError
from app.models.enums import AgentRunStatus
from app.services.llm.prompts import load_prompt
from app.services.llm.provider import (
    LLMError,
    LLMMessage,
    LLMProvider,
    LLMProviderError,
    LLMRequest,
)
from app.services.llm.run_logger import NullRunLogger, RunContext, RunLogger

logger = logging.getLogger(__name__)

T = TypeVar("T", bound=BaseModel)

# A validator returns a list of human-readable problems; empty list means valid.
OutputValidator = Callable[[T], list[str]]


@dataclass
class AgentResult(Generic[T]):
    output: T
    run_id: object | None
    attempts: int
    prompt_version: str
    model: str


class InvalidOutput(Exception):
    def __init__(self, problems: list[str]):
        super().__init__("; ".join(problems))
        self.problems = problems


def _parse_and_validate(content: str, schema: type[T], validator: OutputValidator | None) -> T:
    try:
        data = json.loads(_strip_code_fence(content))
    except json.JSONDecodeError as exc:
        raise InvalidOutput([f"Response is not valid JSON: {exc.msg}"]) from exc
    if not isinstance(data, dict):
        raise InvalidOutput(["Response must be a JSON object"])
    try:
        parsed = schema.model_validate(data)
    except ValidationError as exc:
        problems = [f"{'.'.join(str(p) for p in e['loc']) or '(root)'}: {e['msg']}" for e in exc.errors()]
        raise InvalidOutput(problems) from exc
    if validator:
        problems = validator(parsed)
        if problems:
            raise InvalidOutput(problems)
    return parsed


def _strip_code_fence(content: str) -> str:
    text = content.strip()
    if text.startswith("```"):
        text = text.split("\n", 1)[1] if "\n" in text else ""
        if text.rstrip().endswith("```"):
            text = text.rstrip()[:-3]
    return text.strip()


class LLMService:
    def __init__(
        self,
        provider: LLMProvider,
        model: str,
        run_logger: RunLogger | None = None,
        max_transient_retries: int = 2,
        backoff_seconds: float = 1.0,
    ):
        self.provider = provider
        self.model = model
        self.run_logger = run_logger or NullRunLogger()
        self.max_transient_retries = max_transient_retries
        self.backoff_seconds = backoff_seconds

    def run_structured(
        self,
        *,
        agent_name: str,
        prompt_name: str,
        input_data: dict,
        output_schema: type[T],
        ctx: RunContext | None = None,
        validator: OutputValidator | None = None,
        prompt_version: str | None = None,
    ) -> AgentResult[T]:
        ctx = ctx or RunContext()
        prompt = load_prompt(prompt_name, prompt_version)
        system_prompt = self._system_prompt(prompt.text, output_schema)
        messages = [LLMMessage("user", "INPUT:\n" + json.dumps(input_data, indent=2, default=str))]

        run_id = self.run_logger.start(
            agent_name=agent_name,
            ctx=ctx,
            provider=self.provider.name,
            model=self.model,
            prompt_version=prompt.id,
            input_data=input_data,
        )
        started = time.monotonic()
        attempts = 0
        last_content: str | None = None

        def finish(status: AgentRunStatus, output: dict | None, error: str | None) -> None:
            self.run_logger.finish(
                run_id,
                status=status,
                attempts=attempts,
                output=output,
                error=error,
                latency_ms=int((time.monotonic() - started) * 1000),
            )

        try:
            # First attempt + at most one correction attempt.
            for correction_round in range(2):
                attempts += 1
                request = LLMRequest(
                    agent_name=agent_name,
                    system_prompt=system_prompt,
                    messages=messages,
                    model=self.model,
                    input_data=input_data,
                )
                response = self._call_with_retries(request)
                last_content = response.content
                try:
                    parsed = _parse_and_validate(response.content, output_schema, validator)
                except InvalidOutput as exc:
                    logger.warning("%s produced invalid output (round %s): %s", agent_name, correction_round, exc)
                    if correction_round == 1:
                        raise
                    messages = messages + [
                        LLMMessage("assistant", response.content),
                        LLMMessage(
                            "user",
                            "Your previous response was invalid:\n- "
                            + "\n- ".join(exc.problems)
                            + "\nReturn a corrected JSON object only, matching the schema exactly.",
                        ),
                    ]
                    continue
                finish(AgentRunStatus.SUCCEEDED, parsed.model_dump(mode="json"), None)
                return AgentResult(
                    output=parsed, run_id=run_id, attempts=attempts, prompt_version=prompt.id, model=self.model
                )
        except InvalidOutput as exc:
            error = f"Invalid LLM output after correction retry: {exc}"
            finish(AgentRunStatus.FAILED, {"raw": (last_content or "")[:4000]}, error)
            raise AgentFailedError(f"{agent_name} agent returned invalid output", details={"run_id": str(run_id)}) from exc
        except LLMError as exc:
            finish(AgentRunStatus.FAILED, None, f"{type(exc).__name__}: {exc}")
            raise AgentFailedError(f"{agent_name} agent failed: {exc}", details={"run_id": str(run_id)}) from exc
        raise AssertionError("unreachable")

    def _call_with_retries(self, request: LLMRequest):
        for attempt in range(self.max_transient_retries + 1):
            try:
                return self.provider.complete_json(request)
            except LLMError as exc:
                if not exc.retryable or attempt == self.max_transient_retries:
                    raise
                delay = self.backoff_seconds * (2**attempt)
                logger.warning("Transient LLM error (%s); retrying in %.1fs", exc, delay)
                time.sleep(delay)
        raise AssertionError("unreachable")

    @staticmethod
    def _system_prompt(prompt_text: str, schema: type[BaseModel]) -> str:
        return (
            f"{prompt_text}\n\n"
            "OUTPUT FORMAT: Respond with ONLY a single JSON object (no prose, no markdown) that "
            "validates against this JSON Schema:\n"
            f"{json.dumps(schema.model_json_schema(), indent=2)}"
        )


def build_provider(settings: Settings) -> LLMProvider:
    if settings.llm_provider == "openai":
        from app.services.llm.openai_provider import OpenAIProvider

        return OpenAIProvider(settings.openai_api_key, settings.llm_timeout_seconds)
    if settings.llm_provider == "gemini":
        from app.services.llm.gemini_provider import GeminiLLMProvider

        return GeminiLLMProvider(settings.gemini_api_key or "", settings.llm_timeout_seconds,
                                 base_url=settings.gemini_base_url)
    if settings.llm_provider == "mock":
        from app.services.llm.mock_provider import MockLLMProvider

        return MockLLMProvider()
    raise LLMProviderError(f"Unknown LLM_PROVIDER '{settings.llm_provider}'")


def build_llm_service(settings: Settings | None = None, run_logger: RunLogger | None = None) -> LLMService:
    settings = settings or get_settings()
    if run_logger is None:
        from app.db import SessionLocal
        from app.services.llm.run_logger import DbRunLogger

        run_logger = DbRunLogger(SessionLocal, log_payloads=settings.log_llm_payloads)
    return LLMService(
        provider=build_provider(settings),
        model=settings.resolved_llm_model,
        run_logger=run_logger,
        max_transient_retries=settings.llm_max_transient_retries,
    )
