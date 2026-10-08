"""Regression evaluation for the GrowthOS agents.

Runs every agent against fixed cases in evals/datasets/ and checks behavioural expectations
(no fabrication, unknown when unverifiable, correct classification, ...). Use it whenever a prompt
or model changes:

    python -m evals.run_evals                      # uses LLM_PROVIDER from the environment/.env
    python -m evals.run_evals --provider mock      # offline baseline
    python -m evals.run_evals --suite reply_classification -v

Exit code is non-zero when the pass rate is below --min-pass-rate (default 1.0).
"""
import argparse
import json
import re
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

from app.config import get_settings
from app.errors import AgentFailedError
from app.services.agents import (
    FollowupAgent,
    OutreachAgent,
    QualificationAgent,
    ReplyAnalysisAgent,
    ResearchAgent,
    ResearchInput,
)
from app.services.llm.run_logger import NullRunLogger
from app.services.llm.service import LLMService, build_provider
from app.services.search import EvidenceDoc, StaticResearchTools

DATASETS = Path(__file__).parent / "datasets"
RESULTS = Path(__file__).parent / "results"
SUITES = ["research", "qualification", "outreach", "followup", "reply_classification"]
BUSINESS_PROFILE = json.loads((DATASETS / "business_profile.json").read_text())


def _text(obj) -> str:
    return json.dumps(obj, ensure_ascii=False).lower()


def _contains_any(text: str, needles: list[str]) -> list[str]:
    return [n for n in needles if n.lower() in text.lower()]


# ---------------- per-suite runners: return (output_dict, failures) ----------------
def run_research(llm: LLMService, case: dict) -> tuple[dict, list[str]]:
    docs = [EvidenceDoc(d["url"], d.get("title", ""), d["text"], "website") for d in case["evidence"]]
    agent = ResearchAgent(llm, StaticResearchTools(docs, case.get("evidence_errors")))
    out = agent.run(ResearchInput(**case["input"])).output
    e, fails = case["expect"], []
    if "industry" in e and out.industry.lower() != e["industry"]:
        fails.append(f"industry should be '{e['industry']}', got '{out.industry}'")
    if e.get("industry_not_unknown") and out.industry.lower() == "unknown":
        fails.append("industry should have been identified from the evidence")
    if "company_size" in e and out.company_size.lower() != e["company_size"]:
        fails.append(f"company_size should be '{e['company_size']}', got '{out.company_size}'")
    if "company_size_not_contains" in e and e["company_size_not_contains"] in out.company_size:
        fails.append(f"company_size repeats the unverified claim '{e['company_size_not_contains']}'")
    if "max_confidence" in e and out.confidence > e["max_confidence"]:
        fails.append(f"confidence {out.confidence} > {e['max_confidence']}")
    if "min_confidence" in e and out.confidence < e["min_confidence"]:
        fails.append(f"confidence {out.confidence} < {e['min_confidence']}")
    if e.get("signals_empty") and out.relevant_signals:
        fails.append(f"expected no signals, got {out.relevant_signals}")
    if e.get("signals_nonempty") and not out.relevant_signals:
        fails.append("expected at least one relevant signal")
    if e.get("personalization_empty") and out.personalization_points:
        fails.append(f"expected no personalization points, got {out.personalization_points}")
    if found := _contains_any(_text(out.model_dump()), e.get("must_not_contain", [])):
        fails.append(f"output contains forbidden content: {found}")
    if "output_contains_any" in e and not _contains_any(_text(out.model_dump()), e["output_contains_any"]):
        fails.append(f"output should mention one of {e['output_contains_any']}")
    return out.model_dump(), fails


def run_qualification(llm: LLMService, case: dict) -> tuple[dict, list[str]]:
    agent = QualificationAgent(llm, get_settings().qualification_threshold)
    res = agent.run(business_profile=BUSINESS_PROFILE, lead=case["lead"], research=case["research"],
                    campaign={"objective": "Book discovery calls"})
    out, e, fails = res.result, case["expect"], []
    if "qualified" in e and out.qualified != e["qualified"]:
        fails.append(f"qualified should be {e['qualified']} (score {out.score})")
    if "min_score" in e and out.score < e["min_score"]:
        fails.append(f"score {out.score} < {e['min_score']}")
    if "max_score" in e and out.score > e["max_score"]:
        fails.append(f"score {out.score} > {e['max_score']}")
    for criterion, rating in e.get("ratings", {}).items():
        actual = getattr(res.assessment, criterion).rating
        if actual != rating:
            fails.append(f"{criterion} should be '{rating}', got '{actual}'")
    return out.model_dump(), fails


def _email_checks(out, e: dict) -> list[str]:
    fails = []
    full = f"{out.subject}\n{out.body}"
    if found := _contains_any(full, e.get("must_not_contain", [])):
        fails.append(f"email contains forbidden content: {found}")
    words = len(out.body.split())
    if "max_words" in e and words > e["max_words"]:
        fails.append(f"body has {words} words (> {e['max_words']})")
    if e.get("requires_question") and "?" not in out.body:
        fails.append("no clear question/CTA in the body")
    if "greets_name" in e and e["greets_name"] not in out.body.split("\n")[0]:
        fails.append(f"greeting should use the contact's first name '{e['greets_name']}'")
    if e.get("no_invented_name") and re.match(r"^(hi|hello|dear|hey)\s+(?!there\b|team\b|all\b)[A-Z][a-z]+",
                                               out.body.strip(), re.I) and not re.match(r"^(hi|hello|dear|hey)\s+(there|team|all)\b", out.body.strip(), re.I):
        fails.append(f"greeting appears to invent a name: '{out.body.splitlines()[0]}'")
    if e.get("personalization_empty") and out.personalization_used:
        fails.append(f"no research to personalize from, but used {out.personalization_used}")
    if "subject_prefix" in e and not out.subject.lower().startswith(e["subject_prefix"].lower()):
        fails.append(f"subject should start with '{e['subject_prefix']}'")
    if "final_close_any" in e and not _contains_any(out.body, e["final_close_any"]):
        fails.append("final follow-up should close politely / make 'not now' easy")
    return fails


def run_outreach(llm: LLMService, case: dict) -> tuple[dict, list[str]]:
    context = {"business_profile": BUSINESS_PROFILE, "lead": case["lead"], "contact": case["contact"],
               "research": case["research"], "qualification": case["qualification"],
               "campaign": {"objective": "Book discovery calls"}, "previous_interactions": []}
    out = OutreachAgent(llm).run(context).output
    return out.model_dump(), _email_checks(out, case["expect"])


def run_followup(llm: LLMService, case: dict) -> tuple[dict, list[str]]:
    context = {"business_profile": BUSINESS_PROFILE, "lead": case["lead"], "contact": case["contact"],
               "research": case["research"], "campaign": {"objective": "Book discovery calls"},
               "followup_number": case["followup_number"], "max_followups": case["max_followups"],
               "previous_emails": case["previous_emails"]}
    out = FollowupAgent(llm).run(context).output
    return out.model_dump(), _email_checks(out, case["expect"])


def run_reply(llm: LLMService, case: dict) -> tuple[dict, list[str]]:
    out = ReplyAnalysisAgent(llm).run(original_email=case["original_email"], reply=case["reply"],
                                      lead={"company_name": "Routewise"}).output
    e, fails = case["expect"], []
    if out.classification != e["classification"]:
        fails.append(f"classification should be {e['classification']}, got {out.classification.value}")
    if "requires_human_attention" in e and out.requires_human_attention != e["requires_human_attention"]:
        fails.append(f"requires_human_attention should be {e['requires_human_attention']}")
    return out.model_dump(mode="json"), fails


RUNNERS = {"research": run_research, "qualification": run_qualification, "outreach": run_outreach,
           "followup": run_followup, "reply_classification": run_reply}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--provider", help="Override LLM_PROVIDER (e.g. mock, openai)")
    parser.add_argument("--suite", choices=SUITES, action="append", help="Run only these suites")
    parser.add_argument("--min-pass-rate", type=float, default=1.0)
    parser.add_argument("-v", "--verbose", action="store_true")
    args = parser.parse_args()

    settings = get_settings()
    if args.provider:
        settings = settings.model_copy(update={"llm_provider": args.provider, "llm_model": ""
                                               if args.provider != settings.llm_provider else settings.llm_model})
    llm = LLMService(build_provider(settings), settings.resolved_llm_model, run_logger=NullRunLogger(),
                     max_transient_retries=settings.llm_max_transient_retries)
    print(f"GrowthOS evals — provider={settings.llm_provider} model={settings.resolved_llm_model}\n")

    results, total, passed = [], 0, 0
    for suite in args.suite or SUITES:
        cases = json.loads((DATASETS / f"{suite}.json").read_text())
        suite_passed = 0
        for case in cases:
            started = time.monotonic()
            try:
                output, failures = RUNNERS[suite](llm, case)
            except AgentFailedError as exc:
                output, failures = None, [f"agent failed: {exc.message}"]
            ok = not failures
            suite_passed += ok
            results.append({"suite": suite, "id": case["id"], "description": case["description"], "passed": ok,
                            "failures": failures, "output": output,
                            "latency_ms": int((time.monotonic() - started) * 1000)})
            if not ok or args.verbose:
                print(f"  [{'PASS' if ok else 'FAIL'}] {suite}/{case['id']}: {case['description']}")
                for f in failures:
                    print(f"         - {f}")
        print(f"{suite:<22} {suite_passed}/{len(cases)} passed")
        total += len(cases)
        passed += suite_passed

    rate = passed / total if total else 1.0
    print(f"\nTOTAL {passed}/{total} passed ({rate:.0%})")
    RESULTS.mkdir(exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    out_path = RESULTS / f"eval_{settings.llm_provider}_{stamp}.json"
    out_path.write_text(json.dumps({"provider": settings.llm_provider, "model": settings.resolved_llm_model,
                                    "pass_rate": rate, "results": results}, indent=2, default=str))
    print(f"Results written to {out_path.relative_to(Path.cwd()) if out_path.is_relative_to(Path.cwd()) else out_path}")
    return 0 if rate >= args.min_pass_rate else 1


if __name__ == "__main__":
    sys.exit(main())
