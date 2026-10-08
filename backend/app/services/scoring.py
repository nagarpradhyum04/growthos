"""Deterministic, explainable lead scoring.

The Qualification Agent rates four criteria (strong/partial/none/unknown) with evidence; this module
turns those ratings into a 0-100 score with fixed weights. The LLM never picks the number.
"""
from app.services.agents.schemas import QualificationAssessment, QualificationResult

CRITERIA_WEIGHTS: dict[str, int] = {
    "industry_fit": 30,
    "company_size_fit": 20,
    "pain_point_fit": 30,
    "signal_strength": 20,
}
RATING_MULTIPLIERS: dict[str, float] = {"strong": 1.0, "partial": 0.5, "unknown": 0.2, "none": 0.0}


def score_assessment(assessment: QualificationAssessment, threshold: int) -> QualificationResult:
    breakdown: dict[str, dict] = {}
    total = 0.0
    for criterion, weight in CRITERIA_WEIGHTS.items():
        item = getattr(assessment, criterion)
        points = weight * RATING_MULTIPLIERS[item.rating]
        total += points
        breakdown[criterion] = {
            "rating": item.rating,
            "weight": weight,
            "points": round(points, 1),
            "evidence": item.evidence,
        }
    score = int(round(total))
    disqualified = bool(assessment.disqualifiers)
    qualified = score >= threshold and not disqualified

    reason = assessment.reason
    if disqualified:
        reason = f"Disqualified: {'; '.join(assessment.disqualifiers)}. {reason}"
    elif not qualified:
        reason = f"Score {score} is below the qualification threshold of {threshold}. {reason}"

    breakdown["disqualifiers"] = assessment.disqualifiers
    breakdown["threshold"] = threshold
    return QualificationResult(
        qualified=qualified,
        score=score,
        reason=reason.strip(),
        recommended_angle=assessment.recommended_angle if qualified else "",
        breakdown=breakdown,
    )
