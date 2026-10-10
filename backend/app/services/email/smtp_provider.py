"""SMTP email provider (EMAIL_PROVIDER=smtp) — works with Gmail, Outlook/Office 365, Zoho or any SMTP server.

Gmail: SMTP_HOST=smtp.gmail.com, SMTP_PORT=587, SMTP_USERNAME=you@gmail.com and SMTP_PASSWORD = a Google
"App password" (Google Account → Security → 2-Step Verification → App passwords), not your normal password.
"""
import smtplib
import ssl
from email.message import EmailMessage
from email.utils import formatdate, make_msgid

from app.services.email.base import EmailProvider, EmailSendError, OutgoingEmail, SendResult


class SmtpEmailProvider(EmailProvider):
    name = "smtp"

    def __init__(self, host: str, port: int, username: str, password: str, timeout_seconds: float = 20.0):
        if not host or not username or not password:
            raise EmailSendError("SMTP_HOST, SMTP_USERNAME and SMTP_PASSWORD must be set for EMAIL_PROVIDER=smtp")
        self.host, self.port, self.username, self.password, self.timeout = host, port, username, password, timeout_seconds

    def send(self, message: OutgoingEmail) -> SendResult:
        sender = message.from_address or self.username
        msg = EmailMessage()
        msg["From"] = sender
        msg["To"] = message.to
        msg["Subject"] = message.subject
        msg["Date"] = formatdate(localtime=True)
        # Our email id inside the Message-ID lets the inbox reader match replies (In-Reply-To) exactly.
        domain = sender.rsplit("@", 1)[-1].strip("> ") or "growthos.local"
        msg_id = make_msgid(idstring=f"growthos.{message.idempotency_key}", domain=domain)
        msg["Message-ID"] = msg_id
        msg.set_content(message.body)
        try:
            if self.port == 465:
                with smtplib.SMTP_SSL(self.host, self.port, timeout=self.timeout,
                                      context=ssl.create_default_context()) as s:
                    s.login(self.username, self.password)
                    s.send_message(msg)
            else:
                with smtplib.SMTP(self.host, self.port, timeout=self.timeout) as s:
                    s.starttls(context=ssl.create_default_context())
                    s.login(self.username, self.password)
                    s.send_message(msg)
        except smtplib.SMTPAuthenticationError as exc:
            raise EmailSendError("SMTP login failed: check SMTP_USERNAME and SMTP_PASSWORD (Gmail needs an App "
                                 "password, not your normal password)") from exc
        except smtplib.SMTPRecipientsRefused as exc:
            raise EmailSendError(f"The mail server refused the recipient {message.to}") from exc
        except (smtplib.SMTPException, OSError) as exc:
            raise EmailSendError(f"Could not send through {self.host}:{self.port}: {type(exc).__name__}") from exc
        return SendResult(provider_message_id=msg_id)
