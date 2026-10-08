"""Email Intelligence triage: GREEN (routine) / YELLOW (opportunity) / RED (human attention).

The tier is decided here by deterministic rules over (a) regex detectors on the raw text and (b) the
intents the LLM reported. The LLM can ADD intents but can never lower a tier the rules produced.
RED categories always escalate; YELLOW categories follow the owner's escalation rules.
"""
import re
from dataclasses import dataclass, field

INTENT_VOCAB = [
    "greeting", "thanks", "routine_question", "brochure_request", "meeting_request", "pricing_inquiry",
    "discount_request", "purchase_intent", "large_order", "complaint", "refund", "warranty_dispute", "legal",
    "contract", "sensitive", "opt_out", "out_of_office", "not_interested",
]
RED = {"complaint", "refund", "warranty_dispute", "legal", "contract", "sensitive", "low_confidence"}
YELLOW = {"purchase_intent", "large_order", "pricing_inquiry", "discount_request", "meeting_request"}

LABELS = {
    "complaint": "a complaint / unhappy customer", "refund": "a refund request",
    "warranty_dispute": "a warranty dispute", "legal": "legal language", "contract": "a contract discussion",
    "sensitive": "sensitive content", "low_confidence": "an unclear request (low-confidence classification)",
    "purchase_intent": "purchase intent", "large_order": "a large order", "pricing_inquiry": "a pricing inquiry",
    "discount_request": "a discount request", "meeting_request": "a meeting request",
}

_DETECTORS: dict[str, re.Pattern] = {
    "complaint": re.compile(r"\b(complain\w*|unacceptable|terrible|awful|disappointed|frustrat\w*|angry|furious|"
                            r"worst|not happy|poor service|very unhappy|ridiculous)\b", re.I),
    "refund": re.compile(r"\b(refund\w*|money back|reimburse\w*|chargeback)\b", re.I),
    "warranty_dispute": re.compile(r"\b(warranty (claim )?(was )?(denied|rejected|refused)|should be covered|"
                                   r"not covered under (the )?warranty|dispute)\b", re.I),
    "legal": re.compile(r"\b(lawyer|attorney|legal action|lawsuit|sue you|court|solicitor)\b", re.I),
    "contract": re.compile(r"\b(contract|master service agreement|msa|sla|terms and conditions|purchase agreement)\b", re.I),
    "sensitive": re.compile(r"\b(data breach|privacy violation|harass\w*|discriminat\w*|injur\w*|unsafe|caught fire)\b", re.I),
    "discount_request": re.compile(r"(\b(discount|cheaper|lower (the )?price|best price|coupon|negotiat\w*|price match)\b|\d+\s?% off)", re.I),
    "pricing_inquiry": re.compile(r"\b(price|pricing|cost|quote|quotation|how much)\b", re.I),
    "purchase_intent": re.compile(r"\b((want|ready|like|plan|planning|looking|keen) to (buy|order|purchase)|place an order|"
                                  r"purchase order|move forward|go ahead with)\b", re.I),
    "meeting_request": re.compile(r"\b((set up|schedule|book|have|do) (a )?(call|meeting|demo)|let'?s (talk|meet|chat)|"
                                  r"send (me )?(a )?(calendar|invite))\b", re.I),
    "brochure_request": re.compile(r"\b(brochure|catalog(ue)?|datasheet|spec sheet|send (me )?(some |more )?info(rmation)?)\b", re.I),
    "thanks": re.compile(r"\b(thank(s| you)|much appreciated|cheers)\b", re.I),
    "greeting": re.compile(r"^\s*(hi|hello|hey|good (morning|afternoon))\b", re.I),
}
_QUANTITY = re.compile(r"\b(\d[\d,]*)\s*(units|pieces|pcs|devices|machines|purifiers|seats|licen[cs]es)\b", re.I)
_MONEY = re.compile(r"(?:[$€£]\s?(\d[\d,]*(?:\.\d+)?)\s?(k)?|\b(\d[\d,]*)\s?(usd|eur|gbp|dollars))", re.I)


@dataclass
class Triage:
    tier: str
    intents: list[str]
    reason: str
    escalate: bool
    category: str  # the main escalation category ("" when nothing escalates)
    evidence: dict[str, str] = field(default_factory=dict)  # intent -> matched text


def detect(text: str, large_order_threshold: float = 10000, large_quantity: int = 50) -> dict[str, str]:
    found: dict[str, str] = {}
    for intent, pattern in _DETECTORS.items():
        m = pattern.search(text)
        if m:
            found[intent] = m.group(0).strip()
    for m in _QUANTITY.finditer(text):
        if int(m.group(1).replace(",", "")) >= large_quantity:
            found["large_order"] = m.group(0)
    for m in _MONEY.finditer(text):
        raw = m.group(1) or m.group(3)
        value = float(raw.replace(",", "")) * (1000 if m.group(2) else 1)
        if value >= float(large_order_threshold):
            found["large_order"] = m.group(0).strip()
    # Ordering/pricing words alone are a pricing inquiry, not a discount.
    if "?" in text and not ({"pricing_inquiry", "meeting_request"} & found.keys()):
        found.setdefault("routine_question", "question")
    return found


def triage(text: str, *, llm_intents: list[str] | None = None, classification: str | None = None,
           sentiment: str | None = None, escalation_rules: dict | None = None,
           large_order_threshold: float = 10000) -> Triage:
    evidence = detect(text, large_order_threshold)
    intents = set(evidence) | {i for i in (llm_intents or []) if i in INTENT_VOCAB}
    if sentiment in ("angry", "negative") and {"refund", "warranty_dispute"} & intents:
        intents.add("complaint")
    if classification == "UNSUBSCRIBE":
        intents.add("opt_out")
    if classification == "OUT_OF_OFFICE":
        intents.add("out_of_office")
    if classification == "NOT_INTERESTED":
        intents.add("not_interested")
    if classification == "INTERESTED":
        intents.add("purchase_intent" if "purchase_intent" in intents else "meeting_request")
    if classification == "UNKNOWN" and not intents:
        intents.add("low_confidence")

    ordered = sorted(intents, key=lambda i: (i not in RED, i not in YELLOW, i))
    if "opt_out" in intents:
        return Triage("GREEN", ordered, "Opt-out request: handled automatically by suppression rules (no human needed)",
                      False, "", evidence)

    red = [i for i in ordered if i in RED]
    yellow = [i for i in ordered if i in YELLOW]

    def because(items: list[str]) -> str:
        parts = []
        for i in items:
            snippet = evidence.get(i)
            parts.append(f"{LABELS.get(i, i)}" + (f" (“{snippet}”)" if snippet and snippet != "question" else ""))
        return "; ".join(parts)

    if red:
        return Triage("RED", ordered, f"Escalated because the message contains {because(red)}. "
                      "These always require a human.", True, red[0], evidence)
    if yellow:
        rules = escalation_rules or {}
        to_escalate = [i for i in yellow if rules.get(i, "escalate") != "automate"]
        if to_escalate:
            return Triage("YELLOW", ordered, f"Escalated because the message contains {because(to_escalate)} — "
                          "an important opportunity for the business owner.", True, to_escalate[0], evidence)
        return Triage("YELLOW", ordered, f"Opportunity ({because(yellow)}); your rules allow automation.",
                      False, "", evidence)
    return Triage("GREEN", ordered, "Routine message" + (f" ({', '.join(ordered)})" if ordered else ""),
                  False, "", evidence)
