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


_PRICE_RE = re.compile(r"[$€£₹]\s?\d|\b\d+\s?%\s?off\b|\bdiscount\b|\bfree\b|\bsale\b", re.IGNORECASE)
_SUPERLATIVE_RE = re.compile(r"\b(?:#1|number one|best in the world|guaranteed|100% (?:safe|secure|effective))\b",
                             re.IGNORECASE)


def social_claim_problems(text: str, facts: str) -> list[str]:
    """Deterministic claim checks for promotional copy. `facts` is everything the business told us
    (profile + product catalogue); offers, prices or absolute claims must appear there to be used."""
    problems = []
    lowered = facts.lower()
    for m in _PRICE_RE.finditer(text):
        token = m.group(0).strip().lower()
        if token not in lowered:
            problems.append(f"mentions an offer/price ('{m.group(0).strip()}') that is not in the business facts")
    for m in _SUPERLATIVE_RE.finditer(text):
        if m.group(0).lower() not in lowered:
            problems.append(f"makes an absolute claim ('{m.group(0)}') the business has not stated")
    numbers = set(_NUMBER_RE.findall(text)) - set(_NUMBER_RE.findall(facts))
    if numbers:
        problems.append(f"uses numbers not found in the business facts: {', '.join(sorted(numbers))}")
    return problems


class SocialContentAgent(BaseAgent):
    """Writes one week's promotion: a static image post and a short video post, from business facts only.
    The visual/video prompts it writes are handed to the media provider (Nano Banana / Veo)."""

    name = "social"
    prompt_name = "social"

    def run(self, context: dict, ctx: RunContext | None = None) -> AgentOutput:
        from app.services.agents.schemas import SocialWeekOutput

        facts = json.dumps(context.get("business_profile", {})) + " " + json.dumps(context.get("products", []))

        def validate(out: SocialWeekOutput) -> list[str]:
            problems = []
            for label, text in (("image caption", out.image_post.caption), ("image headline", out.image_post.headline),
                                ("video caption", out.video_post.caption)):
                problems += [f"{label}: {p}" for p in social_claim_problems(text, facts)]
            return problems

        r = self.llm.run_structured(agent_name=self.name, prompt_name=self.prompt_name, input_data=context,
                                    output_schema=SocialWeekOutput, ctx=ctx, validator=validate)
        return AgentOutput(r.output, r.run_id)
