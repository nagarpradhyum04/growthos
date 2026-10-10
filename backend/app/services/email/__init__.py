from app.config import Settings
from app.services.email.base import EmailProvider, EmailSendError, OutgoingEmail, SendResult


def build_email_provider(settings: Settings) -> EmailProvider:
    if settings.email_provider == "resend":
        from app.services.email.resend_provider import ResendEmailProvider

        return ResendEmailProvider(settings.email_api_key)
    if settings.email_provider == "smtp":
        from app.services.email.smtp_provider import SmtpEmailProvider

        return SmtpEmailProvider(settings.smtp_host, settings.smtp_port, settings.smtp_username, settings.smtp_password)
    if settings.email_provider in ("mock", ""):
        from app.services.email.mock_provider import MockEmailProvider

        return MockEmailProvider()
    raise EmailSendError(f"Unknown EMAIL_PROVIDER '{settings.email_provider}'")


__all__ = ["EmailProvider", "EmailSendError", "OutgoingEmail", "SendResult", "build_email_provider"]
