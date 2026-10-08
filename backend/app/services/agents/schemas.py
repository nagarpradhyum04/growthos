"""Pydantic schemas for every agent's structured LLM output.

These are the contract between the LLM and the backend. Anything that fails validation
triggers one correction retry and then a failed agent run.
"""
import re
from typing import Literal

from pydantic import BaseModel, Field, field_validator

from app.models.enums import ReplyClassification

UNKNOWN = "unknown"


def _clean_list(values: list[str]) -> list[str]:
    return [v.strip() for v in values if isinstance(v, str) and v.strip()]


# ---------------- Research ----------------
class SourceCitation(BaseModel):
    claim: str = Field(min_length=1, max_length=500)
    url: str = Field(min_length=1, max_length=1000)


class ResearchOutput(BaseModel):
    company_summary: str = Field(min_length=1, max_length=2000)
    industry: str = Field(min_length=1, max_length=200, description="'unknown' if not verifiable")
    company_size: str = Field(min_length=1, max_length=200, description="'unknown' if not verifiable")
    likely_pain_points: list[str] = Field(default_factory=list, max_length=8)
    relevant_signals: list[str] = Field(default_factory=list, max_length=8)
    personalization_points: list[str] = Field(default_factory=list, max_length=8)
    sources: list[SourceCitation] = Field(default_factory=list, max_length=20)
    confidence: float = Field(ge=0.0, le=1.0)

    _clean = field_validator("likely_pain_points", "relevant_signals", "personalization_points")(
        classmethod(lambda cls, v: _clean_list(v))
    )


# ---------------- Qualification ----------------
Rating = Literal["strong", "partial", "none", "unknown"]


class CriterionAssessment(BaseModel):
    rating: Rating
    evidence: str = Field(max_length=500, description="Short justification citing the research")


class QualificationAssessment(BaseModel):
    """What the LLM returns. The numeric score is computed by the backend (services/scoring.py)."""

    industry_fit: CriterionAssessment
    company_size_fit: CriterionAssessment
    pain_point_fit: CriterionAssessment
    signal_strength: CriterionAssessment
    disqualifiers: list[str] = Field(default_factory=list, max_length=5)
    reason: str = Field(min_length=1, max_length=1000)
    recommended_angle: str = Field(max_length=500)

    _clean = field_validator("disqualifiers")(classmethod(lambda cls, v: _clean_list(v)))


class QualificationResult(BaseModel):
    """Final, explainable qualification (spec output shape + score breakdown)."""

    qualified: bool
    score: int = Field(ge=0, le=100)
    reason: str
    recommended_angle: str
    breakdown: dict


# ---------------- Outreach & Follow-up ----------------
_PLACEHOLDER_RE = re.compile(r"\[[A-Z][A-Za-z ]{1,30}\]|\{\{.*?\}\}|<[A-Z_]{3,}>")


class EmailContentOutput(BaseModel):
    subject: str = Field(min_length=1, max_length=120)
    body: str = Field(min_length=20, max_length=2500)
    personalization_used: list[str] = Field(default_factory=list, max_length=8)
    confidence: float = Field(ge=0.0, le=1.0)

    @field_validator("subject", "body")
    @classmethod
    def _no_placeholders(cls, v: str) -> str:
        if _PLACEHOLDER_RE.search(v):
            raise ValueError("contains an unfilled template placeholder such as [Name] or {{x}}")
        return v.strip()

    @field_validator("body")
    @classmethod
    def _concise(cls, v: str) -> str:
        if len(v.split()) > 220:
            raise ValueError("email body is too long; keep it under 200 words")
        return v

    _clean = field_validator("personalization_used")(classmethod(lambda cls, v: _clean_list(v)))


OutreachOutput = EmailContentOutput
FollowupOutput = EmailContentOutput


# ---------------- Reply analysis ----------------
IntentName = Literal[
    "greeting", "thanks", "routine_question", "brochure_request", "meeting_request", "pricing_inquiry",
    "discount_request", "purchase_intent", "large_order", "complaint", "refund", "warranty_dispute", "legal",
    "contract", "sensitive", "opt_out", "out_of_office", "not_interested",
]
Sentiment = Literal["positive", "neutral", "negative", "angry"]


class ReplyAnalysisOutput(BaseModel):
    classification: ReplyClassification
    summary: str = Field(min_length=1, max_length=1000)
    recommended_action: str = Field(min_length=1, max_length=500)
    requires_human_attention: bool
    # v2 (Email Intelligence) fields; optional so v1 outputs stay valid.
    intents: list[IntentName] = Field(default_factory=list, max_length=8)
    sentiment: Sentiment = "neutral"
    suggested_response: str = Field(default="", max_length=2000)


class MessageAnalysisOutput(BaseModel):
    """Email Intelligence for customer messages. The tier/escalation is decided by backend rules."""

    intents: list[IntentName] = Field(default_factory=list, max_length=8)
    sentiment: Sentiment = "neutral"
    summary: str = Field(min_length=1, max_length=1000)
    recommended_action: str = Field(min_length=1, max_length=500)
    suggested_response: str = Field(default="", max_length=2000)


class SupportAnswerOutput(BaseModel):
    answerable: bool
    answer: str = Field(default="", max_length=3000)
    source_ids: list[str] = Field(default_factory=list, max_length=8)
    escalate: bool = False


class LifecycleMessageOutput(BaseModel):
    subject: str = Field(min_length=1, max_length=150)
    body: str = Field(min_length=10, max_length=1500)

    @field_validator("subject", "body")
    @classmethod
    def _no_placeholders(cls, v: str) -> str:
        if _PLACEHOLDER_RE.search(v):
            raise ValueError("contains an unfilled template placeholder")
        return v.strip()


# ---------------- Analytics ----------------
class AnalyticsOutput(BaseModel):
    summary: str = Field(min_length=1, max_length=2000)
    what_worked: list[str] = Field(default_factory=list, max_length=8)
    what_did_not_work: list[str] = Field(default_factory=list, max_length=8)
    recommendations: list[str] = Field(default_factory=list, max_length=8)
