"""Outreach Agent (initial email) and Follow-up Agent. Both produce editable email drafts."""
import json
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


def _email_validator(context: dict):
    corpus = _research_corpus(context)

    def validate(out: EmailContentOutput) -> list[str]:
        problems = []
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
