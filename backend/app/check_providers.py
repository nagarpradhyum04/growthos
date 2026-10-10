"""CHECK YOUR API KEYS — `python -m app.check_providers [--media] [--send-test-email you@example.com]`

Reads your .env and makes one tiny real request to each configured provider, then says plainly whether it works
and what to fix. Nothing is stored. The image test (--media) and test email (--send-test-email) are opt-in
because they use paid quota / send real mail.
"""
import argparse
import json
import sys

import httpx

from app.config import get_settings
from app.services.llm.provider import LLMMessage, LLMRequest

OK, WARN, FAIL = "OK  ", "WARN", "FAIL"


def _row(status: str, what: str, detail: str) -> tuple[str, str, str]:
    print(f"[{status}] {what:22} {detail}")
    return status, what, detail


def check_llm(s) -> tuple:
    if s.llm_provider == "mock":
        return _row(WARN, "LLM (agents)", "LLM_PROVIDER=mock → agents are offline rule-based stand-ins, no AI. "
                                         "Set LLM_PROVIDER=openai (OPENAI_API_KEY) or gemini (GEMINI_API_KEY).")
    from app.services.llm.service import build_provider

    try:
        provider = build_provider(s)
        out = provider.complete_json(LLMRequest(
            agent_name="healthcheck", model=s.resolved_llm_model, temperature=0,
            system_prompt="You are a health check. Reply with a JSON object only.",
            messages=[LLMMessage("user", 'Return exactly {"ok": true}')]))
        ok = json.loads(out.content).get("ok") is True
        return _row(OK if ok else WARN, "LLM (agents)", f"{s.llm_provider} / {out.model} answered"
                    + ("" if ok else f" but not as asked: {out.content[:80]}"))
    except Exception as exc:  # noqa: BLE001
        return _row(FAIL, "LLM (agents)", f"{s.llm_provider} / {s.resolved_llm_model}: {exc}")


def check_gemini_key(s) -> tuple:
    if not s.gemini_api_key:
        return _row(WARN if s.media_provider == "gemini" or s.llm_provider == "gemini" else OK, "Gemini key",
                    "GEMINI_API_KEY is empty" if s.media_provider == "gemini" or s.llm_provider == "gemini"
                    else "not used")
    url = f"{s.gemini_base_url}/models/gemini-2.5-flash:generateContent"
    try:
        r = httpx.post(url, headers={"x-goog-api-key": s.gemini_api_key}, timeout=30,
                       json={"contents": [{"role": "user", "parts": [{"text": "Reply with the word ok"}]}]})
    except httpx.HTTPError as exc:
        return _row(FAIL, "Gemini key", f"cannot reach {url.split('/v1')[0]}: {type(exc).__name__}")
    where = "Vertex AI (aiplatform.googleapis.com)" if s.resolved_gemini_backend == "vertex" else \
        "Google AI Studio (generativelanguage.googleapis.com)"
    if r.status_code == 200:
        return _row(OK, "Gemini key", f"valid for {where}")
    msg = r.json().get("error", {}).get("message", r.text[:150]) if "json" in r.headers.get("content-type", "") else r.text[:150]
    other = "ai_studio" if s.resolved_gemini_backend == "vertex" else "vertex"
    return _row(FAIL, "Gemini key", f"HTTP {r.status_code} from {where}: {msg[:200]}  "
                f"→ if this key is for the other Google service, set GEMINI_BACKEND={other}")


def check_media(s, run_image: bool) -> tuple:
    if s.media_provider != "gemini":
        return _row(WARN, "Media (social)", "MEDIA_PROVIDER=mock → labelled placeholder images/videos")
    if not run_image:
        return _row(OK, "Media (social)", f"gemini: image {s.gemini_image_model}, video {s.gemini_video_model} "
                    "(run with --media to generate one real test image)")
    from app.services.media.gemini import GeminiMediaProvider

    try:
        res = GeminiMediaProvider(s).generate_image("A simple flat illustration of a green leaf on white.",
                                                    aspect_ratio="1:1", brand={})
        return _row(OK, "Media (social)", f"Nano Banana returned a {len(res.data) // 1024} KB {res.mime} image")
    except Exception as exc:  # noqa: BLE001
        return _row(FAIL, "Media (social)", f"{s.gemini_image_model}: {exc}")


def check_email(s, send_to: str | None) -> tuple:
    if s.email_provider == "mock":
        return _row(WARN, "Email", "EMAIL_PROVIDER=mock → 'sent' emails are recorded but not delivered. "
                                   "For real email: EMAIL_PROVIDER=resend, EMAIL_API_KEY, EMAIL_FROM_ADDRESS")
    if not s.email_api_key or not s.email_from_address:
        return _row(FAIL, "Email", "EMAIL_API_KEY and EMAIL_FROM_ADDRESS are required for resend")
    if not send_to:
        return _row(OK, "Email", f"resend configured, from {s.email_from_address} "
                    "(run with --send-test-email you@example.com to send one)")
    from app.services.email import build_email_provider
    from app.services.email.base import OutgoingEmail

    try:
        import uuid

        build_email_provider(s).send(OutgoingEmail(to=send_to, subject="GrowthOS test email",
                                                   body="If you can read this, real email sending works.",
                                                   from_address=s.email_from_address,
                                                   idempotency_key=f"healthcheck-{uuid.uuid4()}"))
        return _row(OK, "Email", f"test email sent to {send_to}")
    except Exception as exc:  # noqa: BLE001
        return _row(FAIL, "Email", str(exc))


def check_misc(s) -> list[tuple]:
    rows = []
    rows.append(_row(OK if s.search_provider == "tavily" and s.search_api_key else WARN, "Web research",
                     "Tavily web search enabled" if s.search_provider == "tavily" and s.search_api_key else
                     "SEARCH_PROVIDER=none → research uses the lead's website + your notes only (Tavily key optional)"))
    weak = "change-me" in s.jwt_secret or len(s.jwt_secret) < 32
    rows.append(_row(WARN if weak else OK, "JWT_SECRET", "set a long random value (32+ characters)" if weak else "set"))
    rows.append(_row(OK if s.webhook_secret else WARN, "WEBHOOK_SECRET",
                     "set" if s.webhook_secret else "empty → only needed if an email provider posts replies to /webhooks"))
    return rows


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--media", action="store_true", help="also generate one real test image with Nano Banana")
    parser.add_argument("--send-test-email", metavar="ADDRESS", help="also send one real test email")
    args = parser.parse_args()
    s = get_settings()
    print(f"Checking providers from your .env (Gemini endpoint: {s.resolved_gemini_backend})\n")
    rows = [check_llm(s), check_gemini_key(s), check_media(s, args.media), check_email(s, args.send_test_email),
            *check_misc(s)]
    failed = [r for r in rows if r[0] == FAIL]
    print("\n" + ("All configured providers work." if not failed else f"{len(failed)} problem(s) to fix above."))
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
