"""Maps a business owner's command to one of the Orchestrator's supported workflows.

Routing is deterministic (keyword/phrase scoring): every command maps to a known, safe plan, and anything
that can't be mapped is refused with suggestions instead of being guessed by an LLM.
"""
import re
from dataclasses import dataclass, field


@dataclass(frozen=True)
class Command:
    key: str
    label: str
    description: str
    plan: tuple[str, ...]
    phrases: tuple[str, ...] = ()  # weight 2
    words: tuple[str, ...] = ()  # weight 1 (prefix match)
    examples: tuple[str, ...] = ()
    needs_campaign: bool = False


COMMANDS: list[Command] = [
    Command("acquire", "Find & qualify new customers",
            "Research, qualify and draft personalized outreach for the campaign's prospects; drafts wait for your approval.",
            ("understand_goal", "select_candidates", "research", "qualification", "outreach", "safety", "human_review", "summarize"),
            phrases=("find customers", "new customers", "high-quality customers", "find leads", "qualify the", "prepare outreach"),
            words=("find", "prospect", "acquire", "research", "qualif", "outreach", "grow", "new business", "leads"),
            examples=("Find high-quality customers for our business", "Research and qualify the new prospects",
                      "Prepare personalized outreach for this campaign"),
            needs_campaign=True),
    Command("followups", "Follow up with silent leads",
            "Process due follow-ups: the Follow-up Agent drafts the next step, rules stop anyone who replied or opted out.",
            ("select_due_followups", "safety", "followup", "human_review", "summarize"),
            phrases=("follow up", "follow-up", "haven't replied", "have not replied", "no reply", "didn't reply"),
            words=("followup", "chase", "nudge", "remind"),
            examples=("Follow up with leads who haven't replied", "Process due follow-ups now")),
    Command("inbox", "Triage the inbox",
            "Analyze unprocessed replies with Email Intelligence and escalate anything important.",
            ("collect_unanalyzed", "email_intelligence", "escalate", "summarize"),
            phrases=("triage", "new replies", "check the inbox", "check inbox", "analyze replies", "incoming emails"),
            words=("inbox", "replies", "reply", "messages", "emails", "classify"),
            examples=("Triage the inbox and escalate anything important", "Analyze new replies")),
    Command("approvals", "Brief me on pending decisions",
            "Summarize everything waiting for a human decision, most urgent first.",
            ("collect_pending", "prioritize", "summarize"),
            phrases=("needs my attention", "need my attention", "pending decisions", "pending approvals", "what's waiting"),
            words=("approval", "pending", "decision", "attention", "urgent"),
            examples=("What needs my attention today?", "Summarize pending approvals")),
    Command("lifecycle", "Check in with existing customers",
            "Run lifecycle follow-ups (setup help, check-ins, warranty expiry, post-service) within customer preferences and limits.",
            ("select_due_events", "safety", "followup", "summarize"),
            phrases=("existing customers", "check in", "check-in", "warranty reminder", "warranty expir", "after purchase", "after service"),
            words=("lifecycle", "retention", "retain", "warranty", "loyal"),
            examples=("Check in with existing customers", "Send warranty expiry reminders")),
    Command("insights", "Analyze performance & learn",
            "Compute metrics, let the Analytics Agent explain them, and store learnings in shared memory for future campaigns.",
            ("compute_metrics", "analytics", "store_memory"),
            phrases=("what worked", "what works", "performance report", "learn from"),
            words=("analy", "insight", "performance", "learn", "report", "metric", "optimi", "improve"),
            examples=("Analyze campaign performance and learn what works", "Give me a performance report")),
]
BY_KEY = {c.key: c for c in COMMANDS}


@dataclass
class Route:
    command: Command | None
    matched: list[str] = field(default_factory=list)
    alternatives: list[str] = field(default_factory=list)


def route(text: str) -> Route:
    t = " " + re.sub(r"\s+", " ", text.lower()) + " "
    scored = []
    for c in COMMANDS:
        hits = [p for p in c.phrases if p in t]
        hits += [w for w in c.words if re.search(r"\b" + re.escape(w), t)]
        score = 2 * sum(p in t for p in c.phrases) + sum(1 for w in c.words if re.search(r"\b" + re.escape(w), t))
        if score:
            scored.append((score, -COMMANDS.index(c), c, hits))
    if not scored:
        return Route(None)
    scored.sort(reverse=True, key=lambda x: (x[0], x[1]))
    best = scored[0]
    return Route(best[2], best[3], [s[2].key for s in scored[1:3]])


def describe(c: Command) -> dict:
    return {"key": c.key, "label": c.label, "description": c.description, "plan": list(c.plan),
            "examples": list(c.examples), "needs_campaign": c.needs_campaign}
