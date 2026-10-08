"""Research Agent: turns public evidence about a company into a factual research brief."""
from dataclasses import dataclass

from pydantic import BaseModel

from app.services.agents.base import BaseAgent
from app.services.agents.schemas import UNKNOWN, ResearchOutput
from app.services.llm.run_logger import RunContext
from app.services.llm.service import LLMService
from app.services.search import EvidenceBundle, ResearchTools

NOTES_SOURCE = "user-notes"  # pseudo-URL for facts that came from the user's own lead notes
NO_EVIDENCE_MAX_CONFIDENCE = 0.3


class ResearchInput(BaseModel):
    company_name: str
    website: str = ""
    contact_name: str = ""
    contact_role: str = ""
    notes: str = ""


@dataclass
class ResearchAgentResult:
    output: ResearchOutput
    run_id: object | None
    evidence: EvidenceBundle


class ResearchAgent(BaseAgent):
    name = "research"
    prompt_name = "research"

    def __init__(self, llm: LLMService, tools: ResearchTools):
        super().__init__(llm)
        self.tools = tools

    def run(self, data: ResearchInput, ctx: RunContext | None = None) -> ResearchAgentResult:
        evidence = self.tools.gather(data.company_name, data.website)
        documents = [d.to_dict() for d in evidence.documents]
        if data.notes.strip():
            documents.append({"url": NOTES_SOURCE, "title": "Notes provided by the user",
                              "text": data.notes.strip(), "source_type": "user"})
        allowed_urls = {d["url"] for d in documents}

        def validate(out: ResearchOutput) -> list[str]:
            problems = [
                f"sources[{i}].url '{s.url}' is not one of the evidence URLs"
                for i, s in enumerate(out.sources)
                if s.url not in allowed_urls
            ]
            if not documents:
                if out.industry.lower() != UNKNOWN or out.company_size.lower() != UNKNOWN:
                    problems.append("There is no evidence: industry and company_size must be 'unknown'")
                if out.relevant_signals or out.personalization_points:
                    problems.append("There is no evidence: relevant_signals and personalization_points must be empty")
            elif (out.relevant_signals or out.personalization_points) and not out.sources:
                problems.append("relevant_signals/personalization_points require at least one source citation")
            return problems

        result = self.llm.run_structured(
            agent_name=self.name,
            prompt_name=self.prompt_name,
            input_data={
                "lead": data.model_dump(exclude={"notes"}),
                "evidence": documents,
                "evidence_errors": evidence.errors,
            },
            output_schema=ResearchOutput,
            ctx=ctx,
            validator=validate,
        )
        output = result.output
        if not evidence.documents:
            # Deterministic cap: without public evidence the brief can never be high-confidence.
            output.confidence = min(output.confidence, NO_EVIDENCE_MAX_CONFIDENCE)
        return ResearchAgentResult(output=output, run_id=result.run_id, evidence=evidence)
