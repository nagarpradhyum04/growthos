"""Safety Agent / policy layer and Email Intelligence escalation."""
from app.services.escalation import triage
from tests.conftest import lead_to_sent


def _draft(client, auth, lead_id):
    client.post(f"/leads/{lead_id}/research", headers=auth)
    client.post(f"/leads/{lead_id}/qualify", headers=auth)
    return client.post(f"/leads/{lead_id}/generate-email", headers=auth).json()


def _policy(client, auth, **changes):
    p = client.get("/policy", headers=auth).json()
    p.pop("locked_categories")
    p.update(changes)
    r = client.put("/policy", headers=auth, json=p)
    assert r.status_code == 200, r.text
    return r.json()


def test_frequency_limit_blocks_with_explanation(client, auth, lead, email_provider):
    _policy(client, auth, max_messages_per_contact_30d=1)
    sent = lead_to_sent(client, auth, lead["id"])
    from app.db import SessionLocal
    from app.models import Followup
    with SessionLocal() as db:  # make follow-up 1 due now
        from datetime import datetime, timezone
        db.execute(Followup.__table__.update().values(due_at=datetime.now(timezone.utc)))
        db.commit()
    client.post("/followups/process", headers=auth)
    fu = next(e for e in client.get(f"/leads/{lead['id']}", headers=auth).json()["emails"] if e["sequence_number"] == 1)
    client.post(f"/emails/{fu['id']}/approve", headers=auth)
    r = client.post(f"/emails/{fu['id']}/send", headers=auth)
    assert r.status_code == 409
    err = r.json()["error"]
    assert "frequency_limit_reached" in err["details"]["reasons"]
    assert "limit is 1 messages / 30 days" in err["details"]["explanation"]
    assert len(email_provider.outbox) == 1 and sent


def test_blocked_domain_and_banned_phrase(client, auth, lead):
    _policy(client, auth, blocked_domains=["acme-logistics.example"])
    email = _draft(client, auth, lead["id"])
    client.post(f"/emails/{email['id']}/approve", headers=auth)
    review = client.get(f"/emails/{email['id']}", headers=auth).json()
    targeting = next(c for c in review["send_check"]["checks"] if c["key"] == "targeting")
    assert targeting["passed"] is False and "excluded by your targeting rules" in targeting["detail"]
    _policy(client, auth, blocked_domains=[])
    client.put(f"/emails/{email['id']}", headers=auth, json={"subject": "Hi", "body": "Act now for guaranteed results, Jane!"})
    client.post(f"/emails/{email['id']}/approve", headers=auth)
    checks = {c["key"]: c for c in client.get(f"/emails/{email['id']}", headers=auth).json()["send_check"]["checks"]}
    assert checks["content"]["passed"] is False and "banned phrase" in checks["content"]["detail"]


def test_unsupported_claims_escalate_to_human(client, auth, lead):
    from app.db import SessionLocal
    from app.models import Email
    from app.services.policy import evaluate_outbound
    import uuid
    email = _draft(client, auth, lead["id"])
    client.put(f"/emails/{email['id']}", headers=auth,
               json={"subject": "Idea", "body": "Hi Jane, we cut onboarding time by 63% and are the #1 provider. Chat?"})
    with SessionLocal() as db:
        d = evaluate_outbound(db, db.get(Email, uuid.UUID(email["id"])))
    assert d.outcome == "ESCALATE" and "percentage claim" in d.explain()


def test_red_categories_cannot_be_automated(client, auth):
    p = client.get("/policy", headers=auth).json()
    p.pop("locked_categories")
    p["escalation_rules"]["refund"] = "automate"
    assert client.put("/policy", headers=auth, json=p).status_code == 409


def test_triage_tiers():
    assert triage("Thanks a lot!").tier == "GREEN"
    t = triage("We'd like to order 200 units if you can give us a 20% discount.")
    assert t.tier == "YELLOW" and t.escalate and {"discount_request", "large_order"} <= set(t.intents)
    assert "200 units" in t.reason
    red = triage("This is unacceptable. I want a refund or I'll contact my lawyer.")
    assert red.tier == "RED" and red.escalate and "always require a human" in red.reason
    assert triage("ok", classification="UNKNOWN").tier == "RED"
    auto = triage("Can we set up a call?", escalation_rules={"meeting_request": "automate"})
    assert auto.tier == "YELLOW" and not auto.escalate
    # The LLM cannot lower a rule-detected tier.
    assert triage("I demand a refund", llm_intents=["thanks"]).tier == "RED"


def test_reply_escalation_creates_explained_approval(client, auth, lead):
    sent = lead_to_sent(client, auth, lead["id"])
    client.post("/replies?analyze_now=true", headers=auth,
                json={"email_id": sent["id"], "body": "Interesting. Could you do a 15% discount if we order 300 units?"})
    reply = client.get("/replies", headers=auth).json()[0]
    approvals = [a for a in client.get("/approvals", headers=auth).json() if a["type"] == "REPLY_ESCALATION"]
    assert len(approvals) == 1
    a = approvals[0]
    assert a["tier"] == "YELLOW" and "discount" in a["reason"] and "300 units" in a["reason"]
    assert a["suggested_response"] and a["can_automate"] is True
    assert reply["followups_cancelled"] == 1
    r = client.post(f"/approvals/{a['id']}/mark-automated", headers=auth, json={})
    assert r.json()["status"] == "AUTOMATED"
    assert client.get("/policy", headers=auth).json()["escalation_rules"][a["category"]] == "automate"


def test_opt_out_reply_is_not_escalated(client, auth, lead):
    sent = lead_to_sent(client, auth, lead["id"])
    client.post("/replies", headers=auth, json={"email_id": sent["id"], "body": "Unsubscribe me please."})
    assert [a for a in client.get("/approvals", headers=auth).json() if a["type"] == "REPLY_ESCALATION"] == []
    wf = client.get("/workflows", headers=auth, params={"lead_id": lead["id"]}).json()[0]
    assert wf["state"] == "BLOCKED"


def test_approval_reject_and_take_over(client, auth, lead):
    client.post(f"/leads/{lead['id']}/process", headers=auth)
    from app.worker import run_once
    run_once()
    a = client.get("/approvals", headers=auth).json()[0]
    assert client.post(f"/approvals/{a['id']}/reject", headers=auth, json={"note": "Wrong angle"}).json()["status"] == "REJECTED"
    assert client.get(f"/leads/{lead['id']}", headers=auth).json()["emails"] == []
    assert client.post(f"/approvals/{a['id']}/take-over", headers=auth, json={}).status_code == 409
