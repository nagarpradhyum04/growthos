"""End-to-end workflow:
Lead -> Research -> Qualification -> Email -> Approval -> Send -> Reply / Follow-up -> Stop.
"""
import uuid
from datetime import datetime, timedelta, timezone

from sqlalchemy import select

from app.models import AgentRun, Contact, EmailDraft, EmailReply, Followup, Job, ResearchResult, SuppressionRecord
from app.models.enums import JobStatus
from app.services.followup_service import process_due_followups
from app.services.suppression import ERASED, hash_email
from app.worker import run_once
from tests.conftest import create_lead, lead_to_sent


def _future(days: int = 30) -> datetime:
    return datetime.now(timezone.utc) + timedelta(days=days)


def _followups(client, auth, lead_id) -> list[dict]:
    return client.get(f"/leads/{lead_id}", headers=auth).json()["followups"]


def test_full_flow_no_reply_runs_followups_then_stops(client, auth, lead, db, container, email_provider):
    sent = lead_to_sent(client, auth, lead["id"])
    assert sent["status"] == "SENT" and len(email_provider.outbox) == 1

    # Sending scheduled follow-up 1, not due yet.
    pending = _followups(client, auth, lead["id"])
    assert [(f["sequence_number"], f["status"]) for f in pending] == [(1, "PENDING")]
    assert process_due_followups(db, container) == {}

    for step in (1, 2):
        outcomes = process_due_followups(db, container, now=_future())
        assert outcomes == {"generated": 1}
        detail = client.get(f"/leads/{lead['id']}", headers=auth).json()
        followup_email = next(e for e in detail["emails"] if e["sequence_number"] == step)
        assert followup_email["status"] == "DRAFT"  # human approval required by default
        assert followup_email["subject"].startswith("Re: ")
        client.post(f"/emails/{followup_email['id']}/approve", headers=auth)
        assert client.post(f"/emails/{followup_email['id']}/send", headers=auth).json()["status"] == "SENT"

    assert len(email_provider.outbox) == 3
    # Step 3 exceeds MAX_FOLLOWUPS=2: the sequence closes instead of generating anything.
    assert process_due_followups(db, container, now=_future(60)) == {"limit_reached": 1}
    detail = client.get(f"/leads/{lead['id']}", headers=auth).json()
    assert detail["status"] == "COMPLETED"
    assert {e["status"] for e in detail["emails"]} == {"COMPLETED"}
    assert detail["followups"][-1]["status"] == "LIMIT_REACHED"
    assert len(email_provider.outbox) == 3

    runs = {r.agent_name for r in db.scalars(select(AgentRun))}
    assert runs == {"research", "qualification", "outreach", "followup"}


def test_reply_stops_followups_and_is_analyzed(client, auth, lead, db, container, email_provider):
    sent = lead_to_sent(client, auth, lead["id"])
    reply = client.post("/replies", headers=auth, json={
        "email_id": sent["id"], "subject": "Re: Idea", "body": "Sounds interesting, let's set up a call next week."})
    assert reply.status_code == 201
    assert _followups(client, auth, lead["id"])[0]["status"] == "CANCELLED"
    assert _followups(client, auth, lead["id"])[0]["cancel_reason"] == "recipient_replied"

    # Analysis runs in the background worker.
    assert reply.json()["classification"] is None
    run_once()
    analyzed = client.get("/replies", headers=auth).json()[0]
    assert analyzed["classification"] == "INTERESTED" and analyzed["requires_human_attention"]

    detail = client.get(f"/leads/{lead['id']}", headers=auth).json()
    assert detail["status"] == "REPLIED" and detail["emails"][0]["status"] == "REPLIED"
    assert process_due_followups(db, container, now=_future()) == {}
    assert len(email_provider.outbox) == 1


def test_unsubscribe_reply_suppresses_immediately_without_llm(client, auth, lead, campaign, db, container):
    sent = lead_to_sent(client, auth, lead["id"])
    reply = client.post("/replies", headers=auth, json={"email_id": sent["id"], "body": "Please stop emailing me."})
    body = reply.json()
    # The deterministic detector acts before (and independent of) the LLM.
    assert body["classification"] == "UNSUBSCRIBE" and body["opt_out_detected"]
    contact = client.get(f"/leads/{lead['id']}", headers=auth).json()["contacts"][0]
    assert contact["suppressed"] and contact["unsubscribed"]
    assert db.scalar(select(SuppressionRecord.reason)) == "unsubscribed"
    # Cannot be re-imported into any campaign.
    again = client.post("/leads", headers=auth, json={"campaign_id": campaign["id"], "company_name": "Acme",
                                                      "contact_email": "jane@acme-logistics.example"})
    assert again.status_code == 409


def test_llm_detected_unsubscribe_also_suppresses(client, auth, lead, db, container):
    from app.services import reply_service
    from tests.fakes import ScriptedProvider

    sent = lead_to_sent(client, auth, lead["id"])
    # Phrasing the regex detector does not catch; the LLM classifies it as UNSUBSCRIBE.
    reply = client.post("/replies", headers=auth, json={"email_id": sent["id"],
                                                        "body": "This is not something I ever want to hear about again."}).json()
    assert reply["opt_out_detected"] is False
    container.llm.provider = ScriptedProvider({"classification": "UNSUBSCRIBE", "summary": "Wants no contact.",
                                               "recommended_action": "Stop.", "requires_human_attention": False})
    reply_service.analyze_reply(db, db.get(EmailReply, uuid.UUID(reply["id"])), container)
    db.commit()
    assert db.get(Contact, uuid.UUID(sent["contact_id"])).suppressed


def test_llm_cannot_downgrade_detected_unsubscribe(client, auth, lead, db, container):
    from app.services import reply_service
    from tests.fakes import ScriptedProvider

    sent = lead_to_sent(client, auth, lead["id"])
    reply = client.post("/replies", headers=auth, json={"email_id": sent["id"],
                                                        "body": "Interesting, but unsubscribe me please."}).json()
    container.llm.provider = ScriptedProvider({"classification": "INTERESTED", "summary": "x",
                                               "recommended_action": "y", "requires_human_attention": True})
    analyzed = reply_service.analyze_reply(db, db.get(EmailReply, uuid.UUID(reply["id"])), container)
    assert analyzed.classification == "UNSUBSCRIBE"


def test_forget_me_erases_data_and_blocks_forever(client, auth, lead, campaign, db, container, email_provider):
    sent = lead_to_sent(client, auth, lead["id"])
    client.post("/replies", headers=auth, json={"email_id": sent["id"], "body": "Who are you exactly?"})
    run_once()
    contact_id = lead["contacts"][0]["id"]

    response = client.post(f"/contacts/{contact_id}/forget", headers=auth)
    assert response.status_code == 200
    forgotten = response.json()
    assert forgotten["name"] is None and forgotten["email"] is None and forgotten["forgotten_at"]
    assert forgotten["suppressed"] and forgotten["suppression_reason"] == "user_requested_forget"

    db.expire_all()
    # Personal data is gone...
    contact = db.get(Contact, uuid.UUID(contact_id))
    assert contact.email is None and contact.name is None and contact.role is None
    detail = client.get(f"/leads/{lead['id']}", headers=auth).json()
    assert all(e["body"] == ERASED for e in detail["emails"])
    assert all(r["body"] == ERASED for r in detail["replies"])
    assert all(d.body == ERASED for d in db.scalars(select(EmailDraft)))
    assert db.scalar(select(ResearchResult)) is None
    assert all(r.input is None and r.output is None for r in db.scalars(select(AgentRun).where(
        AgentRun.lead_id == uuid.UUID(lead["id"]))))
    assert detail["status"] == "SUPPRESSED"
    # ...only a hash remains, and it is enough to keep blocking.
    record = db.scalar(select(SuppressionRecord))
    assert record.email_hash == hash_email("jane@acme-logistics.example")
    assert "jane" not in str(record.__dict__)

    again = client.post("/leads", headers=auth, json={"campaign_id": campaign["id"], "company_name": "Acme",
                                                      "contact_email": " Jane@ACME-logistics.example "})
    assert again.status_code == 409
    assert client.post(f"/leads/{lead['id']}/research", headers=auth).status_code == 409
    assert process_due_followups(db, container, now=_future()) == {}
    assert len(email_provider.outbox) == 1


def test_forget_me_cancels_pending_followups_and_unsent_drafts(client, auth, lead, db, container, email_provider):
    sent = lead_to_sent(client, auth, lead["id"])
    process_due_followups(db, container, now=_future())  # creates follow-up 1 draft
    detail = client.get(f"/leads/{lead['id']}", headers=auth).json()
    draft = next(e for e in detail["emails"] if e["sequence_number"] == 1)
    client.post(f"/emails/{draft['id']}/approve", headers=auth)

    client.post(f"/contacts/{sent['contact_id']}/forget", headers=auth)
    assert client.get(f"/emails/{draft['id']}", headers=auth).json()["status"] == "SUPPRESSED"
    response = client.post(f"/emails/{draft['id']}/send", headers=auth)
    assert response.status_code == 409
    assert len(email_provider.outbox) == 1


def test_forget_me_request_in_reply_is_enforced(client, auth, lead, db):
    sent = lead_to_sent(client, auth, lead["id"])
    reply = client.post("/replies", headers=auth, json={"email_id": sent["id"],
                                                        "body": "Please delete my data and forget me."}).json()
    assert reply["classification"] == "UNSUBSCRIBE" and reply["body"] == ERASED
    contact = client.get(f"/leads/{lead['id']}", headers=auth).json()["contacts"][0]
    assert contact["forgotten_at"] and contact["email"] is None


def test_paused_campaign_holds_followups_until_resumed(client, auth, lead, campaign, db, container):
    lead_to_sent(client, auth, lead["id"])
    client.post(f"/campaigns/{campaign['id']}/pause", headers=auth)
    assert process_due_followups(db, container, now=_future()) == {}
    assert _followups(client, auth, lead["id"])[0]["status"] == "PENDING"
    client.post(f"/campaigns/{campaign['id']}/resume", headers=auth)
    assert process_due_followups(db, container, now=_future()) == {"generated": 1}


def test_disabled_lead_cancels_followups(client, auth, lead, db, container):
    lead_to_sent(client, auth, lead["id"])
    client.post(f"/leads/{lead['id']}/disable", headers=auth)
    assert _followups(client, auth, lead["id"])[0]["status"] == "CANCELLED"
    assert process_due_followups(db, container, now=_future()) == {}


def test_automated_sending_still_goes_through_can_send(client, auth, lead, campaign, db, container, email_provider):
    client.patch("/organization/settings", headers=auth, json={"automated_sending_enabled": True})
    lead_to_sent(client, auth, lead["id"])
    assert process_due_followups(db, container, now=_future(), limit=1) == {"generated_and_sent": 1}
    assert len(email_provider.outbox) == 2
    db.execute(Followup.__table__.delete())  # keep the rest of the test focused on the second contact
    db.commit()
    # A suppressed contact is still blocked in automated mode.
    other = create_lead(client, auth, campaign, email="max@acme-logistics.example")
    sent = lead_to_sent(client, auth, other["id"])
    db.execute(Followup.__table__.update().where(Followup.contact_id == uuid.UUID(sent["contact_id"]))
               .values(due_at=datetime.now(timezone.utc)))
    db.commit()
    client.post(f"/contacts/{sent['contact_id']}/unsubscribe", headers=auth)
    assert process_due_followups(db, container, now=_future()).get("generated_and_sent") is None
    assert len(email_provider.outbox) == 3


def test_orchestrator_job_runs_pipeline_and_never_sends(client, auth, lead, db, email_provider):
    job = client.post(f"/leads/{lead['id']}/process", headers=auth)
    assert job.status_code == 202
    duplicate = client.post(f"/leads/{lead['id']}/process", headers=auth)
    assert duplicate.json()["id"] == job.json()["id"]  # de-duplicated while queued
    assert run_once()["jobs"] == 1
    result = client.get(f"/jobs/{job.json()['id']}", headers=auth).json()
    assert result["status"] == "SUCCEEDED"
    assert [s["status"] for s in result["result"]["steps"]] == ["done", "done", "done"]
    detail = client.get(f"/leads/{lead['id']}", headers=auth).json()
    assert detail["status"] == "DRAFTED" and detail["emails"][0]["status"] == "DRAFT"
    assert email_provider.outbox == []

    # Re-running skips completed steps instead of calling agents again.
    runs_before = len(client.get("/agent-runs", headers=auth).json())
    client.post(f"/leads/{lead['id']}/process", headers=auth)
    run_once()
    assert len(client.get("/agent-runs", headers=auth).json()) == runs_before


def test_failed_agent_job_is_retried_then_fails(client, auth, lead, db, container):
    from tests.fakes import ScriptedProvider

    container.llm.provider = ScriptedProvider("bad", "bad")
    job = client.post(f"/leads/{lead['id']}/process", headers=auth).json()
    run_once()
    result = client.get(f"/jobs/{job['id']}", headers=auth).json()
    # The orchestrator records the failed step; the lead stays NEW and nothing corrupt is stored.
    assert result["result"]["steps"][0] == {"step": "research", "status": "failed",
                                            "detail": "research agent returned invalid output"}
    assert client.get(f"/leads/{lead['id']}", headers=auth).json()["research"] is None
    failed_run = client.get("/agent-runs", headers=auth).json()[0]
    assert failed_run["status"] == "FAILED"


def test_scheduled_send_is_executed_by_worker(client, auth, lead, db, email_provider):
    client.post(f"/leads/{lead['id']}/research", headers=auth)
    client.post(f"/leads/{lead['id']}/qualify", headers=auth)
    email = client.post(f"/leads/{lead['id']}/generate-email", headers=auth).json()
    client.post(f"/emails/{email['id']}/approve", headers=auth)
    send_at = (datetime.now(timezone.utc) + timedelta(hours=1)).isoformat()
    scheduled = client.post(f"/emails/{email['id']}/send", headers=auth, json={"send_at": send_at}).json()
    assert scheduled["status"] == "SCHEDULED"
    run_once()
    assert email_provider.outbox == []  # not due yet
    db.execute(Job.__table__.update().values(run_at=datetime.now(timezone.utc)))
    db.commit()
    run_once()
    assert client.get(f"/emails/{email['id']}", headers=auth).json()["status"] == "SENT"
    assert len(email_provider.outbox) == 1
    assert db.scalar(select(Job.status)) == JobStatus.SUCCEEDED
