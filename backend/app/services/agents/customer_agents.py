"""Customer-side agents: Email Intelligence (customer messages), Product Support AI, Lifecycle follow-up."""
import json
import re
from dataclasses import dataclass

from app.services.agents.base import BaseAgent
from app.services.agents.schemas import LifecycleMessageOutput, MessageAnalysisOutput, SupportAnswerOutput
from app.services.llm.run_logger import RunContext

_NUMBER_RE = re.compile(r"(?<![\w.])\d+(?:[.,]\d+)?")


@dataclass
class AgentOutput:
    output: object
    run_id: object | None


class EmailIntelligenceAgent(BaseAgent):
    name = "email_intelligence"
    prompt_name = "email_intelligence"

    def run(self, *, message: str, context: dict, ctx: RunContext | None = None) -> AgentOutput:
        r = self.llm.run_structured(agent_name=self.name, prompt_name=self.prompt_name,
                                    input_data={"message": message, "context": context},
                                    output_schema=MessageAnalysisOutput, ctx=ctx)
        return AgentOutput(r.output, r.run_id)


class SupportAgent(BaseAgent):
    """Answers only from retrieved excerpts. Unknown source ids or numbers not in the excerpts are rejected."""

    name = "support"
    prompt_name = "support"

    def run(self, *, question: str, product: dict, excerpts: list[dict], ctx: RunContext | None = None) -> AgentOutput:
        ids = {e["id"] for e in excerpts}

        def validate(out: SupportAnswerOutput) -> list[str]:
            problems = [f"source_id '{s}' is not one of the provided excerpts" for s in out.source_ids if s not in ids]
            if out.answerable:
                if not out.answer.strip():
                    problems.append("answer is empty although answerable=true")
                if not out.source_ids:
                    problems.append("answerable=true requires at least one source_id")
                cited = " ".join(e["text"] for e in excerpts if e["id"] in out.source_ids) + " " + json.dumps(product)
                allowed = set(_NUMBER_RE.findall(cited))
                invented = sorted(set(_NUMBER_RE.findall(out.answer)) - allowed)
                if invented:
                    problems.append(f"numbers not found in the cited excerpts: {', '.join(invented)}")
            return problems

        r = self.llm.run_structured(agent_name=self.name, prompt_name=self.prompt_name,
                                    input_data={"question": question, "product": product, "excerpts": excerpts},
                                    output_schema=SupportAnswerOutput, ctx=ctx, validator=validate)
        return AgentOutput(r.output, r.run_id)


class LifecycleAgent(BaseAgent):
    name = "lifecycle"
    prompt_name = "lifecycle"

    def run(self, context: dict, ctx: RunContext | None = None) -> AgentOutput:
        r = self.llm.run_structured(agent_name=self.name, prompt_name=self.prompt_name, input_data=context,
                                    output_schema=LifecycleMessageOutput, ctx=ctx)
        return AgentOutput(r.output, r.run_id)
