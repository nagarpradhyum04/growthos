"""Resend (https://resend.com) email provider. EMAIL_PROVIDER=resend, EMAIL_API_KEY, EMAIL_FROM_ADDRESS."""
import httpx

from app.services.email.base import EmailProvider, EmailSendError, OutgoingEmail, SendResult


class ResendEmailProvider(EmailProvider):
    name = "resend"
    URL = "https://api.resend.com/emails"

    def __init__(self, api_key: str, timeout_seconds: float = 15.0):
        if not api_key:
            raise EmailSendError("EMAIL_API_KEY is not set")
        self._api_key = api_key
        self._timeout = timeout_seconds

    def send(self, message: OutgoingEmail) -> SendResult:
        if not message.from_address:
            raise EmailSendError("EMAIL_FROM_ADDRESS is not set")
        try:
            response = httpx.post(
                self.URL,
                headers={
                    "Authorization": f"Bearer {self._api_key}",
                    "Idempotency-Key": message.idempotency_key,
                },
                json={
                    "from": message.from_address,
                    "to": [message.to],
                    "subject": message.subject,
                    "text": message.body,
                },
                timeout=self._timeout,
            )
        except httpx.HTTPError as exc:
            raise EmailSendError(f"Email provider unreachable: {type(exc).__name__}") from exc
        if response.status_code >= 400:
            raise EmailSendError(f"Email provider rejected the message (HTTP {response.status_code})")
        return SendResult(provider_message_id=response.json().get("id", ""))
