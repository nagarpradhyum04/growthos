"""can_send() and the hard business rules. These must hold no matter what any agent outputs."""
import uuid
from datetime import datetime, timezone

from app.models import Campaign, Contact, Email, Lead, SuppressionRecord
from app.models.enums import CampaignStatus, EmailStatus
from app.services.safety import can_send
from app.services.suppression import hash_email
from tests.conftest import create_lead, lead_to_sent


def _approved_email(client, auth, lead_id) -> dict:
    client.post(f"/leads/{lead_id}/research", headers=auth)
    client.post(f"/leads/{lead_id}/qualify", headers=auth)
    email = client.post(f"/leads/{lead_id}/generate-email", headers=auth).json()
    return client.post(f"/emails/{email['id']}/approve", headers=auth).json()


def _reasons(db, email_id) -> list[str]:
    return can_send(db, db.get(Email, uuid.UUID(email_id))).reasons


def test_approved_email_to_clean_contact_is_allowed(client, auth, lead, db):
    email = _approved_email(client, auth, lead["id"])
    assert _reasons(db, email["id"]) == []


def test_draft_cannot_be_sent_without_approval(client, auth, lead, email_provider):
    client.post(f"/leads/{lead['id']}/research", headers=auth)
    client.post(f"/leads/{lead['id']}/qualify", headers=auth)
    email = client.post(f"/leads/{lead['id']}/generate-email", headers=auth).json()
    response = client.post(f"/emails/{email['id']}/send", headers=auth)
    assert response.status_code == 409
    assert "not_approved" in response.json()["error"]["details"]["reasons"]
    assert email_provider.outbox == []


def test_suppressed_contact_cannot_receive_email(client, auth, lead, db, email_provider):
    email = _approved_email(client, auth, lead["id"])
    contact = db.get(Contact, uuid.UUID(lead["contacts"][0]["id"]))
    contact.suppressed = True
    db.commit()
    response = client.post(f"/emails/{email['id']}/send", headers=auth)
    assert response.status_code == 409
    assert "contact_suppressed" in response.json()["error"]["details"]["reasons"]
    assert email_provider.outbox == []
    db.expire_all()
    assert db.get(Email, uuid.UUID(email["id"])).status == EmailStatus.SUPPRESSED


def test_unsubscribed_contact_cannot_receive_email(client, auth, lead, email_provider):
    email = _approved_email(client, auth, lead["id"])
    assert client.post(f"/contacts/{lead['contacts'][0]['id']}/unsubscribe", headers=auth).status_code == 200
    response = client.post(f"/emails/{email['id']}/send", headers=auth)
    assert response.status_code == 409
    reasons = response.json()["error"]["details"]["reasons"]
    assert "contact_unsubscribed" in reasons and "suppression_record_exists" in reasons
    assert email_provider.outbox == []


def test_suppression_record_alone_blocks_even_if_contact_flags_are_reset(client, auth, lead, db, email_provider):
    """Deleting/resetting profile data must not make the person contactable again."""
    email = _approved_email(client, auth, lead["id"])
    contact = db.get(Contact, uuid.UUID(lead["contacts"][0]["id"]))
    db.add(SuppressionRecord(organization_id=contact.organization_id, email_hash=contact.email_hash, reason="manual"))
    contact.suppressed = False
    contact.unsubscribed = False
    db.commit()
    assert "suppression_record_exists" in _reasons(db, email["id"])
    assert client.post(f"/emails/{email['id']}/send", headers=auth).status_code == 409
    assert email_provider.outbox == []


def test_paused_campaign_cannot_send(client, auth, campaign, lead, email_provider):
    email = _approved_email(client, auth, lead["id"])
    assert client.post(f"/campaigns/{campaign['id']}/pause", headers=auth).json()["status"] == "PAUSED"
    response = client.post(f"/emails/{email['id']}/send", headers=auth)
    assert response.status_code == 409
    assert "campaign_paused" in response.json()["error"]["details"]["reasons"]
    # Pausing is temporary: the email is not suppressed and can go out after resuming.
    client.post(f"/campaigns/{campaign['id']}/resume", headers=auth)
    assert client.post(f"/emails/{email['id']}/send", headers=auth).status_code == 200
    assert len(email_provider.outbox) == 1


def test_disabled_lead_cannot_send(client, auth, lead, email_provider):
    email = _approved_email(client, auth, lead["id"])
    client.post(f"/leads/{lead['id']}/disable", headers=auth)
    response = client.post(f"/emails/{email['id']}/send", headers=auth)
    assert "lead_disabled" in response.json()["error"]["details"]["reasons"]
    assert email_provider.outbox == []


def test_followup_limit_is_enforced(client, auth, lead, db):
    sent = lead_to_sent(client, auth, lead["id"])
    campaign = db.get(Campaign, uuid.UUID(sent["campaign_id"]))
    # Fabricate an approved step beyond the limit (MAX_FOLLOWUPS=2) and check the gate.
    beyond = Email(organization_id=campaign.organization_id, campaign_id=campaign.id,
                   lead_id=uuid.UUID(lead["id"]), contact_id=uuid.UUID(sent["contact_id"]), sequence_number=3,
                   subject="s", body="b", status=EmailStatus.APPROVED, approved_at=datetime.now(timezone.utc))
    db.add(beyond)
    db.commit()
    assert "followup_limit_reached" in can_send(db, beyond).reasons
    campaign.max_followups = 5
    db.commit()
    assert "followup_limit_reached" not in can_send(db, beyond).reasons


def test_sent_email_cannot_be_sent_twice(client, auth, lead, email_provider):
    sent = lead_to_sent(client, auth, lead["id"])
    response = client.post(f"/emails/{sent['id']}/send", headers=auth)
    assert response.status_code == 409
    assert "already_sent" in response.json()["error"]["details"]["reasons"]
    assert len(email_provider.outbox) == 1


def test_duplicate_contact_in_same_campaign_is_blocked(client, auth, campaign, lead, db, email_provider):
    # The API refuses to add the same person twice to a campaign...
    response = client.post("/leads", headers=auth, json={
        "campaign_id": campaign["id"], "company_name": "Acme again", "contact_email": "JANE@acme-logistics.example"})
    assert response.status_code == 409
    # ...and even if a duplicate row slips in (e.g. a race), can_send blocks the second email.
    sent = lead_to_sent(client, auth, lead["id"])
    org_id = db.get(Lead, uuid.UUID(lead["id"])).organization_id
    dup_lead = Lead(organization_id=org_id, campaign_id=uuid.UUID(campaign["id"]), company_name="Dup")
    db.add(dup_lead)
    db.flush()
    dup_contact = Contact(organization_id=org_id, lead_id=dup_lead.id, email="jane@acme-logistics.example",
                          email_hash=hash_email("jane@acme-logistics.example"))
    db.add(dup_contact)
    db.flush()
    dup_email = Email(organization_id=org_id, campaign_id=uuid.UUID(campaign["id"]), lead_id=dup_lead.id,
                      contact_id=dup_contact.id, sequence_number=0, subject="s", body="b",
                      status=EmailStatus.APPROVED, approved_at=datetime.now(timezone.utc))
    db.add(dup_email)
    db.commit()
    assert "duplicate_email" in can_send(db, dup_email).reasons
    assert len(email_provider.outbox) == 1 and sent


def test_followup_blocked_after_reply(client, auth, lead, db):
    sent = lead_to_sent(client, auth, lead["id"])
    client.post("/replies", headers=auth, json={"email_id": sent["id"], "body": "Thanks, let me think about it."})
    org_id = db.get(Lead, uuid.UUID(lead["id"])).organization_id
    followup = Email(organization_id=org_id, campaign_id=uuid.UUID(sent["campaign_id"]), lead_id=uuid.UUID(lead["id"]),
                     contact_id=uuid.UUID(sent["contact_id"]), sequence_number=1, subject="s", body="b",
                     status=EmailStatus.APPROVED, approved_at=datetime.now(timezone.utc))
    db.add(followup)
    db.commit()
    assert "recipient_replied" in can_send(db, followup).reasons


def test_email_provider_failure_marks_failed_and_allows_retry(client, auth, lead, email_provider):
    email = _approved_email(client, auth, lead["id"])
    email_provider.fail_next = True
    response = client.post(f"/emails/{email['id']}/send", headers=auth)
    assert response.status_code == 502
    assert "Traceback" not in response.text
    assert client.get(f"/emails/{email['id']}", headers=auth).json()["status"] == "FAILED"
    retry = client.post(f"/emails/{email['id']}/send", headers=auth)
    assert retry.status_code == 200 and retry.json()["status"] == "SENT"
    assert len(email_provider.outbox) == 1


def test_editing_an_approved_email_requires_reapproval(client, auth, lead):
    email = _approved_email(client, auth, lead["id"])
    edited = client.put(f"/emails/{email['id']}", headers=auth,
                        json={"subject": "New subject", "body": "Hi Jane,\n\nA shorter, edited body.\n\nSam"})
    assert edited.json()["status"] == "DRAFT" and edited.json()["edited_by_human"] is True
    assert client.post(f"/emails/{email['id']}/send", headers=auth).status_code == 409


def test_suppressed_email_cannot_be_added_as_new_lead(client, auth, campaign, lead):
    client.post(f"/contacts/{lead['contacts'][0]['id']}/unsubscribe", headers=auth)
    other = client.post("/campaigns", headers=auth, json={"name": "Another campaign"}).json()
    response = client.post("/leads", headers=auth, json={
        "campaign_id": other["id"], "company_name": "Acme", "contact_email": "jane@acme-logistics.example"})
    assert response.status_code == 409


def test_unqualified_lead_gets_no_draft(client, auth, campaign, research_tools):
    research_tools._documents = []  # no evidence -> everything unknown -> low score
    lead = create_lead(client, auth, campaign, email="bob@unknown.example", company_name="Mystery Co",
                       website="")
    client.post(f"/leads/{lead['id']}/research", headers=auth)
    q = client.post(f"/leads/{lead['id']}/qualify", headers=auth).json()
    assert q["qualified"] is False and q["score"] < 60
    response = client.post(f"/leads/{lead['id']}/generate-email", headers=auth)
    assert response.status_code == 409
