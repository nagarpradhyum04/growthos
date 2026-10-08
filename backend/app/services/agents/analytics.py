"""Analytics Agent: explains campaign metrics. A deterministic check rejects invented numbers."""
import json
import re
from dataclasses import dataclass

from app.services.agents.base import BaseAgent
from app.services.agents.schemas import AnalyticsOutput
from app.services.llm.run_logger import RunContext

_NUMBER_RE = re.compile(r"(?<![\w.])\d+(?:\.\d+)?")


def _numbers(text: str) -> set[str]:
    return {n.rstrip("0").rstrip(".") if "." in n else n for n in _NUMBER_RE.findall(text)}


@dataclass
class AnalyticsResult:
    output: AnalyticsOutput
    run_id: object | None


class AnalyticsAgent(BaseAgent):
    name = "analytics"
    prompt_name = "analytics"

    def run(self, metrics: dict, ctx: RunContext | None = None) -> AnalyticsResult:
        input_data = {"metrics": metrics}
        allowed = _numbers(json.dumps(input_data))

        def validate(out: AnalyticsOutput) -> list[str]:
            text = " ".join([out.summary, *out.what_worked, *out.what_did_not_work, *out.recommendations])
            invented = sorted(_numbers(text) - allowed)
            if invented:
                return [f"These numbers do not appear in the metrics and must not be used: {', '.join(invented)}"]
            return []

        result = self.llm.run_structured(
            agent_name=self.name,
            prompt_name=self.prompt_name,
            input_data=input_data,
            output_schema=AnalyticsOutput,
            ctx=ctx,
            validator=validate,
        )
        return AnalyticsResult(output=result.output, run_id=result.run_id)
