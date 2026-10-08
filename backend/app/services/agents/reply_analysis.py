"""Reply Analysis Agent: classifies inbound replies."""
from dataclasses import dataclass

from app.services.agents.base import BaseAgent
from app.services.agents.schemas import ReplyAnalysisOutput
from app.services.llm.run_logger import RunContext


@dataclass
class ReplyAnalysisResult:
    output: ReplyAnalysisOutput
    run_id: object | None


class ReplyAnalysisAgent(BaseAgent):
    name = "reply_analysis"
    prompt_name = "reply_analysis"

    def run(self, *, original_email: dict, reply: dict, lead: dict,
            ctx: RunContext | None = None) -> ReplyAnalysisResult:
        result = self.llm.run_structured(
            agent_name=self.name,
            prompt_name=self.prompt_name,
            input_data={"original_email": original_email, "reply": reply, "lead": lead},
            output_schema=ReplyAnalysisOutput,
            ctx=ctx,
        )
        return ReplyAnalysisResult(output=result.output, run_id=result.run_id)
