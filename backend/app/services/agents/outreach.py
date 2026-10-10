"""Outreach Agent (initial email) and Follow-up Agent. Both produce editable email drafts."""
import json
import re
from dataclasses import dataclass

from app.services.agents.base import BaseAgent, contains_email_address, ungrounded_items
from app.services.agents.schemas import EmailContentOutput
from app.services.llm.run_logger import RunContext


@dataclass
class EmailAgentResult:
    output: EmailContentOutput
    run_id: object | None


def _research_corpus(context: dict) -> str:
    research = context.get("research") or {}
    return " ".join(
        [
            research.get("company_summary", ""),
            " ".join(research.get("relevant_signals", [])),
            " ".join(research.get("personalization_points", [])),
            " ".join(research.get("likely_pain_points", [])),
            json.dumps(context.get("lead", {})),
        ]
    )


# Claims an email may only make if the business itself stated them (profile) — never invented by the writer.
_SOCIAL_PROOF_RE = re.compile(
    r"\b(many|most|lots of|hundreds of|thousands of|our|other) (teams|customers|clients|companies|businesses|clinics|"
    r"practices|partners|people) (tell|told|say|said|report|reported|love|trust|swear)\b", re.I)
_OFFER_RE = re.compile(r"\d+\s?%\s?(off|discount)|\bdiscount\b|\bguarantee(d)?\b|\bfree (trial|month|installation|shipping)\b|"
                       r"\brisk-free\b|\bno[- ]risk\b|[$€£₹]\s?\d", re.I)


def email_claim_problems(text: str, context: dict) -> list[str]:
    """Deterministic anti-fabrication checks for sales emails (independent of the model)."""
    profile = json.dumps(context.get("business_profile", {})).lower()
    problems = []
    for m in _SOCIAL_PROOF_RE.finditer(text):
        problems.append(f"Unsupported social-proof claim '{m.group(0)}': only state what the business profile says")
    for m in _OFFER_RE.finditer(text):
        if m.group(0).lower() not in profile:
            problems.append(f"Offer/price/guarantee '{m.group(0)}' is not in the business profile; do not invent offers")
    return problems


def _email_validator(context: dict):
    corpus = _research_corpus(context)

    def validate(out: EmailContentOutput) -> list[str]:
        problems = email_claim_problems(f"{out.subject}\n{out.body}", context)
        if contains_email_address(out.body):
            problems.append("The body must not contain email addresses")
        for item in ungrounded_items(out.personalization_used, corpus):
            problems.append(
                f"personalization_used item '{item}' is not supported by the research; only use research facts"
            )
        return problems

    return validate


class OutreachAgent(BaseAgent):
    name = "outreach"
    prompt_name = "outreach"

    def run(self, context: dict, ctx: RunContext | None = None) -> EmailAgentResult:
        """context: business_profile, lead, contact, research, qualification, campaign, previous_interactions"""
        result = self.llm.run_structured(
            agent_name=self.name,
            prompt_name=self.prompt_name,
            input_data=context,
            output_schema=EmailContentOutput,
            ctx=ctx,
            validator=_email_validator(context),
        )
        return EmailAgentResult(output=result.output, run_id=result.run_id)


class FollowupAgent(BaseAgent):
    name = "followup"
    prompt_name = "followup"

    def run(self, context: dict, ctx: RunContext | None = None) -> EmailAgentResult:
        """context: business_profile, lead, contact, research, campaign, followup_number, max_followups,
        previous_emails"""
        result = self.llm.run_structured(
            agent_name=self.name,
            prompt_name=self.prompt_name,
            input_data=context,
            output_schema=EmailContentOutput,
            ctx=ctx,
            validator=_email_validator(context),
        )
        return EmailAgentResult(output=result.output, run_id=result.run_id)
