from abc import ABC, abstractmethod
from dataclasses import dataclass


@dataclass
class OutgoingEmail:
    to: str
    subject: str
    body: str
    from_address: str
    idempotency_key: str  # our email id: lets providers de-duplicate retried requests


@dataclass
class SendResult:
    provider_message_id: str


class EmailSendError(Exception):
    pass


class EmailProvider(ABC):
    name: str

    @abstractmethod
    def send(self, message: OutgoingEmail) -> SendResult:
        """Raise EmailSendError on failure."""
