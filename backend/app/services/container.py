"""Wires external adapters (LLM, research tools, email) once, so tests can swap them."""
from dataclasses import dataclass

from app.config import Settings, get_settings
from app.services.agents import (
    AnalyticsAgent,
    FollowupAgent,
    OutreachAgent,
    QualificationAgent,
    ReplyAnalysisAgent,
    ResearchAgent,
)
from app.services.email import EmailProvider, build_email_provider
from app.services.media import MediaProvider, build_media_provider
from app.services.llm.service import LLMService, build_llm_service
from app.services.search import ResearchTools, build_research_tools


@dataclass
class Container:
    settings: Settings
    llm: LLMService
    research_tools: ResearchTools
    email_provider: EmailProvider
    media_provider: MediaProvider | None = None

    # Agents are cheap wrappers; build on demand so they always use the current adapters.
    def research_agent(self) -> ResearchAgent:
        return ResearchAgent(self.llm, self.research_tools)

    def qualification_agent(self) -> QualificationAgent:
        return QualificationAgent(self.llm, self.settings.qualification_threshold)

    def outreach_agent(self) -> OutreachAgent:
        return OutreachAgent(self.llm)

    def followup_agent(self) -> FollowupAgent:
        return FollowupAgent(self.llm)

    def reply_analysis_agent(self) -> ReplyAnalysisAgent:
        return ReplyAnalysisAgent(self.llm)

    def analytics_agent(self) -> AnalyticsAgent:
        return AnalyticsAgent(self.llm)

    def email_intelligence_agent(self):
        from app.services.agents.customer_agents import EmailIntelligenceAgent

        return EmailIntelligenceAgent(self.llm)

    def support_agent(self):
        from app.services.agents.customer_agents import SupportAgent

        return SupportAgent(self.llm)

    def lifecycle_agent(self):
        from app.services.agents.customer_agents import LifecycleAgent

        return LifecycleAgent(self.llm)

    def social_agent(self):
        from app.services.agents.customer_agents import SocialContentAgent

        return SocialContentAgent(self.llm)

    def media(self) -> MediaProvider:
        if self.media_provider is None:
            self.media_provider = build_media_provider(self.settings)
        return self.media_provider


_container: Container | None = None


def get_container() -> Container:
    global _container
    if _container is None:
        settings = get_settings()
        _container = Container(
            settings=settings,
            llm=build_llm_service(settings),
            research_tools=build_research_tools(settings),
            email_provider=build_email_provider(settings),
        )
    return _container


def set_container(container: Container | None) -> None:
    """Test hook."""
    global _container
    _container = container
