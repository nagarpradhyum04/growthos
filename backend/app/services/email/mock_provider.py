"""MOCK EMAIL ADAPTER — logs instead of sending. Selected with EMAIL_PROVIDER=mock.

Sent messages are kept in memory (`outbox`) so tests can assert on them. Nothing leaves the machine.
"""
import logging
import uuid

from app.services.email.base import EmailProvider, EmailSendError, OutgoingEmail, SendResult

logger = logging.getLogger(__name__)


class MockEmailProvider(EmailProvider):
    name = "mock"

    def __init__(self) -> None:
        self.outbox: list[OutgoingEmail] = []
        self.fail_next = False  # test hook: simulate a provider failure

    def send(self, message: OutgoingEmail) -> SendResult:
        if self.fail_next:
            self.fail_next = False
            raise EmailSendError("Simulated email provider failure")
        self.outbox.append(message)
        logger.info("[mock email] to=%s subject=%r", message.to, message.subject)
        return SendResult(provider_message_id=f"mock-{uuid.uuid4()}")
