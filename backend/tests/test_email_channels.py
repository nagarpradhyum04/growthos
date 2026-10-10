"""Real email channels: SMTP sending (e.g. Gmail app password) and importing replies from the mailbox (IMAP)."""
from email.message import EmailMessage

import pytest

from app.services.email.base import EmailSendError, OutgoingEmail
from app.services.email.imap_inbox import import_message, new_text
from tests.conftest import lead_to_sent


class FakeSMTP:
    sent: list = []
    fail_login = False

    def __init__(self, host, port, timeout=None, context=None):
        self.host, self.port = host, port

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def starttls(self, context=None):
        pass

    def login(self, user, password):
        import smtplib

        if FakeSMTP.fail_login:
            raise smtplib.SMTPAuthenticationError(535, b"bad credentials")

    def send_message(self, msg):
        FakeSMTP.sent.append(msg)


def test_smtp_provider_sends_with_traceable_message_id(monkeypatch):
    import smtplib

    from app.services.email.smtp_provider import SmtpEmailProvider

    FakeSMTP.sent, FakeSMTP.fail_login = [], False
    monkeypatch.setattr(smtplib, "SMTP", FakeSMTP)
    p = SmtpEmailProvider("smtp.gmail.com", 587, "me@gmail.com", "app-password")
    res = p.send(OutgoingEmail(to="pat@clinic.example", subject="Hello", body="Hi Pat", from_address="",
                               idempotency_key="11111111-2222-3333-4444-555555555555"))
    msg = FakeSMTP.sent[0]
    assert msg["From"] == "me@gmail.com" and msg["To"] == "pat@clinic.example"
    assert "growthos.11111111-2222-3333-4444-555555555555" in res.provider_message_id == msg["Message-ID"]
    FakeSMTP.fail_login = True
    with pytest.raises(EmailSendError, match="App password"):
        p.send(OutgoingEmail(to="x@y.example", subject="s", body="b", from_address="", idempotency_key="k"))
    with pytest.raises(EmailSendError):
        SmtpEmailProvider("", 587, "", "")


def test_quoted_history_is_removed_from_replies():
    body = "Yes, let's talk Tuesday.\n\nOn Mon, 5 Oct 2026, Sam <sam@x.example> wrote:\n> Hi Pat,\n> old text"
    assert new_text(body) == "Yes, let's talk Tuesday."


def _reply(to_msg_id: str | None, from_addr: str, body: str, message_id: str) -> bytes:
    m = EmailMessage()
    m["From"] = f"Jane Doe <{from_addr}>"
    m["To"] = "me@gmail.com"
    m["Subject"] = "Re: Idea"
    m["Message-ID"] = message_id
    if to_msg_id:
        m["In-Reply-To"] = to_msg_id
    m.set_content(body)
    return bytes(m)


def test_mailbox_reply_is_matched_imported_once_and_stops_followups(client, auth, lead, db):
    sent = lead_to_sent(client, auth, lead["id"])
    raw = _reply(f"<1.growthos.{sent['id']}@gmail.com>", "someone-else@other.example",
                 "Sounds interesting, can we set up a call?\n\nOn Mon wrote:\n> old", "<r1@mail.example>")
    assert import_message(db, raw) == "recorded"
    assert import_message(db, raw) == "duplicate"  # polling again never double-imports
    detail = client.get(f"/leads/{lead['id']}", headers=auth).json()
    assert detail["status"] == "REPLIED"
    assert all(f["status"] != "PENDING" for f in detail["followups"])
    reply = client.get("/replies", headers=auth).json()[0]
    assert reply["body"].startswith("Sounds interesting") and "old" not in reply["body"]


def test_mailbox_reply_matched_by_sender_and_unrelated_mail_ignored(client, auth, lead, db):
    lead_to_sent(client, auth, lead["id"])
    assert import_message(db, _reply(None, "jane@acme-logistics.example", "Please stop emailing me.", "<r2@x>")) == "recorded"
    contact = client.get(f"/leads/{lead['id']}", headers=auth).json()["contacts"][0]
    assert contact["suppressed"] is True  # opt-out rule applied on import
    assert import_message(db, _reply(None, "newsletter@shop.example", "50% off today!", "<r3@x>")) == "ignored"
