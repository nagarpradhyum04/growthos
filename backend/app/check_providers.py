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


def _net(exc: Exception) -> str:
    import socket

    if isinstance(exc, socket.gaierror):
        return "host not found (check the host name and your internet connection)"
    if isinstance(exc, (TimeoutError, socket.timeout)):
        return "timed out (a firewall or network may be blocking this port)"
    if isinstance(exc, ConnectionRefusedError):
        return "connection refused (wrong port?)"
    return type(exc).__name__


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
    used = s.media_provider == "gemini" or s.llm_provider == "gemini"
    if not s.gemini_api_key:
        return _row(WARN if used else OK, "Gemini key", "GEMINI_API_KEY is empty" if used else "not used")
    from app.services.gemini_client import AI_STUDIO, GeminiClient, GeminiHTTPError, pick_model

    client = GeminiClient(s.gemini_api_key, backend=s.resolved_gemini_backend, timeout=30)
    model = s.resolved_llm_model if s.llm_provider == "gemini" else "gemini-flash-latest"
    try:
        r, used_model = client.call_model(model, "generateContent", {
            "contents": [{"role": "user", "parts": [{"text": "Reply with the word ok"}]}]}, "text")
    except GeminiHTTPError as exc:
        return _row(FAIL, "Gemini key", str(exc))
    except httpx.HTTPError as exc:
        return _row(FAIL, "Gemini key", f"cannot reach Google: {type(exc).__name__}")
    where = "Google AI Studio" if client.base == AI_STUDIO else "Vertex AI"
    if r.status_code != 200:
        hint = {400: "the key is not valid", 401: "the key is not valid", 403: "the key has no access (enable the "
                "Gemini API / billing for this key's project)", 429: "quota exhausted or rate limited"}.get(r.status_code, "")
        return _row(FAIL, "Gemini key", f"HTTP {r.status_code} from {where}: {GeminiClient.error_message(r)}"
                    + (f" → {hint}" if hint else ""))
    models = client.list_models()
    picks = {k: pick_model(models, k) for k in ("text", "image", "video")} if models else {}
    note = f" (configured '{model}' is unavailable; using '{used_model}' — set LLM_MODEL={used_model})" \
        if used_model != model else ""
    avail = (f"; best available → text: {picks.get('text') or '-'}, image: {picks.get('image') or '-'}, "
             f"video: {picks.get('video') or '-'}") if picks else ""
    return _row(OK, "Gemini key", f"valid for {where}, model {used_model} answered{note}{avail}")


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
        return _row(WARN, "Email (sending)", "EMAIL_PROVIDER=mock → 'sent' emails are recorded but NOT delivered. "
                    "For real email set EMAIL_PROVIDER=smtp with SMTP_HOST/SMTP_USERNAME/SMTP_PASSWORD "
                    "(e.g. Gmail + App password), or EMAIL_PROVIDER=resend with EMAIL_API_KEY")
    if s.email_provider == "resend" and (not s.email_api_key or not s.email_from_address):
        return _row(FAIL, "Email (sending)", "EMAIL_API_KEY and EMAIL_FROM_ADDRESS are required for resend")
    if s.email_provider == "smtp":
        import smtplib
        import ssl

        if not (s.smtp_host and s.smtp_username and s.smtp_password):
            return _row(FAIL, "Email (sending)", "SMTP_HOST, SMTP_USERNAME and SMTP_PASSWORD are required for smtp")
        try:
            if s.smtp_port == 465:
                conn = smtplib.SMTP_SSL(s.smtp_host, s.smtp_port, timeout=20, context=ssl.create_default_context())
            else:
                conn = smtplib.SMTP(s.smtp_host, s.smtp_port, timeout=20)
                conn.starttls(context=ssl.create_default_context())
            conn.login(s.smtp_username, s.smtp_password)
            conn.quit()
        except smtplib.SMTPAuthenticationError:
            return _row(FAIL, "Email (sending)", f"{s.smtp_host} rejected the login for {s.smtp_username}. Gmail needs "
                        "an App password (Google Account → Security → 2-Step Verification → App passwords)")
        except (smtplib.SMTPException, OSError) as exc:
            return _row(FAIL, "Email (sending)", f"cannot connect to {s.smtp_host}:{s.smtp_port}: {_net(exc)}")
    if not send_to:
        return _row(OK, "Email (sending)", f"{s.email_provider} ready"
                    + (f", sending as {s.smtp_username}" if s.email_provider == "smtp" else f", from {s.email_from_address}"))
    import uuid

    from app.services.email import build_email_provider
    from app.services.email.base import OutgoingEmail
    from app.services.email_service import sender_address

    try:
        build_email_provider(s).send(OutgoingEmail(to=send_to, subject="GrowthOS test email",
                                                   body="If you can read this, real email sending works.",
                                                   from_address=sender_address(s, "GrowthOS"),
                                                   idempotency_key=f"healthcheck-{uuid.uuid4()}"))
        return _row(OK, "Email (sending)", f"test email sent to {send_to}: check that inbox (and spam)")
    except Exception as exc:  # noqa: BLE001
        return _row(FAIL, "Email (sending)", str(exc))


def check_inbox(s) -> tuple:
    if not s.imap_host:
        return _row(WARN, "Email (replies)", "IMAP_HOST not set → replies are not read automatically. For Gmail set "
                    "IMAP_HOST=imap.gmail.com (uses your SMTP login), or add replies from the Inbox page")
    import imaplib

    try:
        box = imaplib.IMAP4_SSL(s.imap_host, s.imap_port)
        box.login(s.imap_username or s.smtp_username, s.imap_password or s.smtp_password)
        status, _ = box.select(s.imap_folder, readonly=True)
        box.logout()
        if status != "OK":
            return _row(FAIL, "Email (replies)", f"folder {s.imap_folder!r} not found")
        return _row(OK, "Email (replies)", f"reading replies from {s.imap_host} every {s.imap_poll_seconds}s")
    except imaplib.IMAP4.error as exc:
        return _row(FAIL, "Email (replies)", f"IMAP login failed: {exc}. For Gmail enable IMAP and use an App password")
    except OSError as exc:
        return _row(FAIL, "Email (replies)", f"cannot reach {s.imap_host}:{s.imap_port}: {_net(exc)}")


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


def run_checks(s, *, media: bool = False, send_to: str | None = None) -> list[tuple]:
    return [check_llm(s), check_gemini_key(s), check_media(s, media), check_email(s, send_to), check_inbox(s),
            *check_misc(s)]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--media", action="store_true", help="also generate one real test image with Nano Banana")
    parser.add_argument("--send-test-email", metavar="ADDRESS", help="also send one real test email")
    args = parser.parse_args()
    s = get_settings()
    print(f"Checking providers from your .env (Gemini endpoint: {s.resolved_gemini_backend})\n")
    rows = run_checks(s, media=args.media, send_to=args.send_test_email)
    failed = [r for r in rows if r[0] == FAIL]
    print("\n" + ("All configured providers work." if not failed else f"{len(failed)} problem(s) to fix above."))
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
