"""MOCK LLM ADAPTER — deterministic, offline, rule-based stand-in for a real LLM.

Selected with LLM_PROVIDER=mock. It exists so the whole system (API, worker, UI, tests, evals)
runs locally without an API key. It is intentionally simple and conservative: it only uses the
structured input it is given and says "unknown" when evidence is missing. It is NOT a substitute
for a real model's quality — run the eval suite against a real provider before trusting prompts.
"""
import json
import re

from app.services.llm.provider import LLMProvider, LLMProviderError, LLMRequest, LLMResponse

_INDUSTRY_KEYWORDS = [
    ("e-commerce", "E-commerce"),
    ("ecommerce", "E-commerce"),
    ("online store", "E-commerce"),
    ("logistics", "Logistics"),
    ("freight", "Logistics"),
    ("healthcare", "Healthcare"),
    ("clinic", "Healthcare"),
    ("fintech", "Financial services"),
    ("payments", "Financial services"),
    ("bank", "Financial services"),
    ("manufactur", "Manufacturing"),
    ("marketing agency", "Marketing services"),
    ("agency", "Marketing services"),
    ("saas", "Software"),
    ("software", "Software"),
    ("platform", "Software"),
    ("education", "Education"),
    ("restaurant", "Hospitality"),
    ("real estate", "Real estate"),
]

_PAIN_POINTS = {
    "Software": ["Building a predictable sales pipeline", "Converting trial users to paying customers"],
    "E-commerce": ["Rising customer acquisition costs", "Retaining repeat customers"],
    "Logistics": ["Managing operational efficiency at scale", "Winning new shipper accounts"],
    "Healthcare": ["Reducing administrative workload", "Patient acquisition and retention"],
    "Financial services": ["Customer acquisition in a regulated market", "Building trust with new customers"],
    "Manufacturing": ["Finding new distribution partners", "Managing supply chain costs"],
    "Marketing services": ["Winning new clients consistently", "Demonstrating ROI to clients"],
}

_SIGNAL_RE = re.compile(r"\b(hiring|launch|launched|announc|raised|funding|expan|opened|new office|partnership|acquired)", re.I)
_SIZE_RE = re.compile(r"(\d[\d,]*)\s*\+?\s*(?:employees|people|team members|staff)", re.I)
_CLOSED_RE = re.compile(r"\b(ceased operations|shut down|no longer operating|permanently closed|out of business)\b", re.I)


def _sentences(text: str) -> list[str]:
    return [s.strip() for s in re.split(r"(?<=[.!?])\s+", text) if len(s.strip()) > 15]


def _words(text: str) -> set[str]:
    return {w for w in re.findall(r"[a-z]{5,}", text.lower())}


class MockLLMProvider(LLMProvider):
    name = "mock"

    def complete_json(self, request: LLMRequest) -> LLMResponse:
        handler = getattr(self, f"_{request.agent_name}", None)
        if handler is None:
            raise LLMProviderError(f"Mock provider has no handler for agent '{request.agent_name}'")
        return LLMResponse(content=json.dumps(handler(request.input_data)), model="mock-model")

    # ---------------- research ----------------
    def _research(self, data: dict) -> dict:
        lead = data.get("lead", {})
        evidence = [e for e in data.get("evidence", []) if e.get("text", "").strip()]
        name = lead.get("company_name", "The company")
        if not evidence:
            return {
                "company_summary": f"No verifiable public information was found for {name}.",
                "industry": "unknown",
                "company_size": "unknown",
                "likely_pain_points": [],
                "relevant_signals": [],
                "personalization_points": [],
                "sources": [],
                "confidence": 0.1,
            }
        all_text = " ".join(e["text"] for e in evidence)
        primary = evidence[0]
        summary = " ".join(_sentences(primary["text"])[:2]) or primary["text"][:300]
        industry = next((label for kw, label in _INDUSTRY_KEYWORDS if kw in all_text.lower()), "unknown")
        size_match = _SIZE_RE.search(all_text)
        size = f"about {size_match.group(1)} employees" if size_match else "unknown"

        signals, sources = [], []
        for doc in evidence:
            for sentence in _sentences(doc["text"]):
                if _SIGNAL_RE.search(sentence) and len(signals) < 4:
                    signals.append(sentence[:200])
                    sources.append({"claim": sentence[:200], "url": doc["url"]})
        if _CLOSED_RE.search(all_text):
            signals.append("The company appears to have ceased operations.")
            sources.append({"claim": "The company appears to have ceased operations.", "url": primary["url"]})
        sources.insert(0, {"claim": summary[:200], "url": primary["url"]})
        personalization = signals[:2] or _sentences(primary["text"])[:1]
        confidence = min(0.75, 0.4 + 0.1 * len(signals) + (0.05 if industry != "unknown" else 0))
        return {
            "company_summary": summary[:1500],
            "industry": industry,
            "company_size": size,
            "likely_pain_points": _PAIN_POINTS.get(industry, []),
            "relevant_signals": signals,
            "personalization_points": [p[:200] for p in personalization],
            "sources": sources,
            "confidence": round(confidence, 2),
        }

    # ---------------- qualification ----------------
    def _qualification(self, data: dict) -> dict:
        profile = data.get("business_profile", {})
        research = data.get("research") or {}
        industry = (research.get("industry") or "unknown").lower()
        targets = [i.lower() for i in profile.get("industries", [])]

        if industry == "unknown":
            industry_fit = ("unknown", "Research could not verify the industry.")
        elif any(t in industry or industry in t for t in targets):
            industry_fit = ("strong", f"Industry '{research.get('industry')}' is a target industry.")
        else:
            industry_fit = ("none", f"Industry '{research.get('industry')}' is not a target industry.")

        size_fit = ("unknown", "Company size is unknown.")
        size_match = re.search(r"\d[\d,]*", research.get("company_size") or "")
        if size_match:
            n = int(size_match.group(0).replace(",", ""))
            size_fit = ("none", f"About {n} employees is outside the target sizes.")
            for target in profile.get("target_company_sizes", []):
                nums = [int(x) for x in re.findall(r"\d+", target)]
                if (len(nums) == 2 and nums[0] <= n <= nums[1]) or (len(nums) == 1 and n >= nums[0]):
                    size_fit = ("strong", f"About {n} employees fits target size {target}.")
                    break

        pains = research.get("likely_pain_points") or []
        offer_words = _words(" ".join([profile.get("products_services", ""), profile.get("value_proposition", "")]))
        overlap = _words(" ".join(pains)) & offer_words
        if not pains:
            pain_fit = ("unknown", "No pain points identified in research.")
        elif len(overlap) >= 2:
            pain_fit = ("strong", f"Pain points overlap with the offer ({', '.join(sorted(overlap)[:3])}).")
        elif overlap:
            pain_fit = ("partial", f"Some overlap with the offer ({', '.join(sorted(overlap))}).")
        else:
            pain_fit = ("none", "Pain points do not relate to the offer.")

        signals = research.get("relevant_signals") or []
        if len(signals) >= 2:
            signal_fit = ("strong", f"{len(signals)} relevant signals found.")
        elif signals:
            signal_fit = ("partial", "One relevant signal found.")
        else:
            signal_fit = ("unknown", "No verifiable signals.")

        disqualifiers = []
        if any(_CLOSED_RE.search(s) or "ceased operations" in s.lower() for s in signals):
            disqualifiers.append("The company appears to have ceased operations.")
        own_name = (profile.get("company_name") or "").lower()
        if own_name and own_name == (data.get("lead", {}).get("company_name") or "").lower():
            disqualifiers.append("The lead is the business itself.")

        fits = [industry_fit, size_fit, pain_fit, signal_fit]
        good = sum(1 for f in fits if f[0] in ("strong", "partial"))
        reason = (
            f"{good} of 4 criteria show a fit based on available research."
            if research.get("confidence", 0) >= 0.3
            else "Research found too little verifiable information to judge fit."
        )
        return {
            "industry_fit": {"rating": industry_fit[0], "evidence": industry_fit[1]},
            "company_size_fit": {"rating": size_fit[0], "evidence": size_fit[1]},
            "pain_point_fit": {"rating": pain_fit[0], "evidence": pain_fit[1]},
            "signal_strength": {"rating": signal_fit[0], "evidence": signal_fit[1]},
            "disqualifiers": disqualifiers,
            "reason": reason,
            "recommended_angle": (pains[0] if pains and not disqualifiers else ""),
        }

    # ---------------- outreach / follow-up ----------------
    @staticmethod
    def _greeting(contact: dict) -> str:
        name = (contact or {}).get("name") or ""
        return f"Hi {name.split()[0]}," if name.strip() else "Hi there,"

    @staticmethod
    def _signoff(profile: dict) -> str:
        return profile.get("sender_name") or profile.get("company_name") or "The team"

    def _outreach(self, data: dict) -> dict:
        profile = data.get("business_profile", {})
        lead = data.get("lead", {})
        research = data.get("research") or {}
        qualification = data.get("qualification") or {}
        company = lead.get("company_name", "your company")
        points = research.get("personalization_points") or []
        angle = qualification.get("recommended_angle") or "growing your customer base"
        value = profile.get("value_proposition") or profile.get("products_services") or "help teams like yours grow"

        lines = [self._greeting(data.get("contact", {})), ""]
        if points:
            lines.append(f"I came across {company} and noticed this: {points[0].rstrip('.')}.")
        else:
            lines.append(f"I'm reaching out because {company} looks like a company we may be able to help.")
        lines += [
            f"Teams in a similar position often find {angle[0].lower() + angle[1:]} challenging. "
            f"{profile.get('company_name') or 'We'} can help: {value.rstrip('.')}.",
            "",
            "Would you be open to a 15-minute call next week to see if this is relevant?",
            "",
            "Best,",
            self._signoff(profile),
        ]
        return {
            "subject": f"Idea for {company}"[:120],
            "body": "\n".join(lines),
            "personalization_used": points[:1],
            "confidence": 0.7 if points else 0.4,
        }

    def _followup(self, data: dict) -> dict:
        profile = data.get("business_profile", {})
        previous = data.get("previous_emails") or []
        last_subject = previous[-1]["subject"] if previous else "Following up"
        subject = last_subject if last_subject.lower().startswith("re:") else f"Re: {last_subject}"
        is_last = data.get("followup_number") == data.get("max_followups")
        pains = (data.get("research") or {}).get("likely_pain_points") or []
        angle = (
            f"One more thought: many teams tell us {pains[-1][0].lower() + pains[-1][1:]} is where they lose the most time."
            if pains
            else f"A quick note in case my previous email got buried: {profile.get('value_proposition') or 'we may be able to help'}."
        )
        closing = (
            "If now isn't the right time, no problem at all - just let me know and I won't follow up again."
            if is_last
            else "Would a short call be useful?"
        )
        body = "\n".join([self._greeting(data.get("contact", {})), "", angle, "", closing, "", "Best,", self._signoff(profile)])
        return {"subject": subject[:120], "body": body, "personalization_used": [], "confidence": 0.6}

    # ---------------- reply analysis ----------------
    _RULES = [
        ("UNSUBSCRIBE", r"unsubscribe|remove me|take me off|stop (emailing|contacting|sending)|do not (contact|email)|don't (contact|email)|forget me|delete my (data|information)|opt.?out"),
        ("OUT_OF_OFFICE", r"out of (the )?office|on vacation|on leave|away until|auto.?reply|automatic reply|limited access to email"),
        ("REQUESTED_LATER", r"next (quarter|month|year)|in a few (weeks|months)|reach out (again )?(later|in)|circle back|not right now but|later this year|after (january|february|march|april|may|june|july|august|september|october|november|december)"),
        ("NOT_INTERESTED", r"not interested|no thanks|no thank you|not a fit|already (have|use|work with)|we'll pass|not for us|no need"),
        ("INTERESTED", r"interested|sounds (good|great)|let'?s (talk|chat|connect)|book a|schedule|happy to (chat|talk)|set up a (call|meeting)|send (me )?(a )?(calendar|invite)|demo"),
    ]

    def _reply_analysis(self, data: dict) -> dict:
        reply = data.get("reply", {})
        text = f"{reply.get('subject', '')}\n{reply.get('body', '')}".lower()
        classification = "UNKNOWN"
        for label, pattern in self._RULES:
            if re.search(pattern, text):
                classification = label
                break
        if classification == "UNKNOWN" and "?" in text:
            classification = "ASKED_QUESTION"
        actions = {
            "INTERESTED": "Reply promptly and propose meeting times.",
            "NOT_INTERESTED": "Thank them and close the lead; no further follow-ups.",
            "ASKED_QUESTION": "Answer their question personally.",
            "REQUESTED_LATER": "Set a reminder to reach out at the requested time.",
            "UNSUBSCRIBE": "Do not contact this person again.",
            "OUT_OF_OFFICE": "No action needed; wait until they are back.",
            "UNKNOWN": "Read the reply and decide manually.",
        }
        snippet = " ".join((reply.get("body") or "").split())[:160]
        return {
            "classification": classification,
            "summary": f"The contact replied: \"{snippet}\"" if snippet else "The reply was empty.",
            "recommended_action": actions[classification],
            "requires_human_attention": classification in {"INTERESTED", "ASKED_QUESTION", "REQUESTED_LATER", "UNKNOWN"},
        }

    # ---------------- analytics ----------------
    def _analytics(self, data: dict) -> dict:
        m = data.get("metrics", {}).get("overall", {})
        sent, replies = m.get("emails_sent", 0), m.get("replies", 0)
        if sent == 0:
            return {
                "summary": "No emails have been sent yet, so there is no performance data to analyze.",
                "what_worked": [],
                "what_did_not_work": [],
                "recommendations": ["Research and qualify leads, then review and send the first drafts."],
            }
        summary = f"{sent} emails were sent and {replies} replies were received (reply rate {m.get('reply_rate_pct')}%)."
        if sent < 10:
            summary += " This is too little data to draw firm conclusions."
        worked = [f"{replies} contacts replied."] if replies else []
        not_worked = [] if replies else ["No replies have been received yet."]
        recs = ["Keep reviewing drafts for specific, evidence-based personalization."]
        if m.get("leads_qualified", 0) < m.get("leads_total", 0):
            recs.append("Focus outreach on qualified leads only.")
        return {"summary": summary, "what_worked": worked, "what_did_not_work": not_worked, "recommendations": recs}
