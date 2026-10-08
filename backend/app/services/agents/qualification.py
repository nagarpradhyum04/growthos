"""Lead Qualification Agent: LLM rates criteria with evidence; backend computes the score."""
from dataclasses import dataclass

from app.services.agents.base import BaseAgent
from app.services.agents.schemas import UNKNOWN, QualificationAssessment, QualificationResult
from app.services.llm.run_logger import RunContext
from app.services.llm.service import LLMService
from app.services.scoring import score_assessment


@dataclass
class QualificationAgentResult:
    result: QualificationResult
    assessment: QualificationAssessment
    run_id: object | None


class QualificationAgent(BaseAgent):
    name = "qualification"
    prompt_name = "qualification"

    def __init__(self, llm: LLMService, threshold: int):
        super().__init__(llm)
        self.threshold = threshold

    def run(self, *, business_profile: dict, lead: dict, research: dict, campaign: dict,
            ctx: RunContext | None = None) -> QualificationAgentResult:
        def validate(a: QualificationAssessment) -> list[str]:
            problems = []
            if str(research.get("industry", UNKNOWN)).lower() == UNKNOWN and a.industry_fit.rating in ("strong", "partial"):
                problems.append("industry_fit must be 'unknown' because research.industry is unknown")
            if str(research.get("company_size", UNKNOWN)).lower() == UNKNOWN and a.company_size_fit.rating in ("strong", "partial"):
                problems.append("company_size_fit must be 'unknown' because research.company_size is unknown")
            if not research.get("relevant_signals") and a.signal_strength.rating in ("strong", "partial"):
                problems.append("signal_strength cannot be positive: research has no relevant_signals")
            return problems

        result = self.llm.run_structured(
            agent_name=self.name,
            prompt_name=self.prompt_name,
            input_data={"business_profile": business_profile, "lead": lead, "research": research, "campaign": campaign},
            output_schema=QualificationAssessment,
            ctx=ctx,
            validator=validate,
        )
        return QualificationAgentResult(
            result=score_assessment(result.output, self.threshold), assessment=result.output, run_id=result.run_id
        )
