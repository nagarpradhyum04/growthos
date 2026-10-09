"""Customer portal sign-in (Business ID + email + code) and Orchestrator commands."""
from app.worker import run_once
from tests.conftest import lead_to_sent, make_product_and_customer, register


def _business_id(client, auth) -> str:
    return client.get("/auth/me", headers=auth).json()["organization"]["business_code"]


def test_owner_sees_business_id_and_portal_url(client, auth):
    org = client.get("/auth/me", headers=auth).json()["organization"]
    assert org["business_code"].startswith("GOS-") and len(org["business_code"]) == 10
    assert org["portal_url"].startswith("http")


def test_registered_customer_gets_code_and_access(client, auth, email_provider):
    product, customer, purchase, portal = make_product_and_customer(client, auth)
    assert client.get("/portal/products", headers=portal).json()[0]["purchase_id"] == purchase["id"]
    sent = [m for m in email_provider.outbox if "sign-in code" in m.subject]
    assert sent and sent[0].to == "pat@clinic.example"
    # The Access Agent's check is visible to the owner in the trace.
    trace = client.get("/trace", headers=auth).json()
    assert any(e["agent"] == "access" and e["status"] == "COMPLETED" for e in trace)


def test_unregistered_email_gets_no_code_and_same_message(client, auth, email_provider):
    make_product_and_customer(client, auth)
    bid = _business_id(client, auth)
    ok = client.post("/portal-auth/request", json={"business_id": bid, "email": "pat@clinic.example"}).json()
    bad = client.post("/portal-auth/request", json={"business_id": bid, "email": "stranger@x.example"}).json()
    assert "dev_code" not in bad and bad["message"] == ok["message"]  # no account enumeration
    r = client.post("/portal-auth/verify", json={"request_id": bad["request_id"], "code": "123456"})
    assert r.status_code == 401
    trace = client.get("/trace", headers=auth).json()
    denied = next(e for e in trace if e["agent"] == "access" and e["status"] == "BLOCKED")
    assert "registered customer" in denied["result"]


def test_wrong_business_id_and_other_business_customer(client, auth):
    make_product_and_customer(client, auth)
    assert "dev_code" not in client.post("/portal-auth/request", json={"business_id": "GOS-XXXXXX",
                                                                       "email": "pat@clinic.example"}).json()
    other = register(client, "boss@other.example", "Other")
    other_bid = _business_id(client, other)
    # A customer of business A cannot sign in to business B's portal.
    assert "dev_code" not in client.post("/portal-auth/request", json={"business_id": other_bid,
                                                                       "email": "pat@clinic.example"}).json()


def test_wrong_code_attempts_lock_the_request(client, auth):
    make_product_and_customer(client, auth)
    req = client.post("/portal-auth/request", json={"business_id": _business_id(client, auth),
                                                    "email": "pat@clinic.example"}).json()
    wrong = "000000" if req["dev_code"] != "000000" else "111111"
    for _ in range(5):
        assert client.post("/portal-auth/verify", json={"request_id": req["request_id"], "code": wrong}).status_code == 401
    assert client.post("/portal-auth/verify", json={"request_id": req["request_id"], "code": req["dev_code"]}).status_code == 401
    # Codes are single-use too.
    req2 = client.post("/portal-auth/request", json={"business_id": _business_id(client, auth),
                                                     "email": "pat@clinic.example"}).json()
    assert client.post("/portal-auth/verify", json={"request_id": req2["request_id"], "code": req2["dev_code"]}).status_code == 200
    assert client.post("/portal-auth/verify", json={"request_id": req2["request_id"], "code": req2["dev_code"]}).status_code == 401


def test_customers_cannot_use_owner_login(client, auth):
    make_product_and_customer(client, auth)
    from app.db import SessionLocal
    from app.models import User
    from app.security import hash_password
    from sqlalchemy import select
    with SessionLocal() as db:
        u = db.scalar(select(User).where(User.email == "pat@clinic.example"))
        u.password_hash = hash_password("some-password-1")
        db.commit()
    r = client.post("/auth/login", json={"email": "pat@clinic.example", "password": "some-password-1"})
    assert r.status_code == 403 and "customer portal" in r.json()["detail"].lower()


def test_opted_out_customer_is_denied(client, auth, campaign, lead):
    from tests.conftest import lead_to_sent as _send
    product = client.post("/products", headers=auth, json={"name": "P", "warranty_months": 12}).json()
    _send(client, auth, lead["id"])
    client.post(f"/leads/{lead['id']}/convert", headers=auth, json={"product_id": product["id"]})
    client.post(f"/contacts/{lead['contacts'][0]['id']}/unsubscribe", headers=auth)
    r = client.post("/portal-auth/request", json={"business_id": _business_id(client, auth),
                                                  "email": "jane@acme-logistics.example"}).json()
    assert "dev_code" not in r


# ---------------- Orchestrator commands ----------------
def test_commands_are_listed_and_routed(client, auth):
    cmds = client.get("/workflows/commands", headers=auth).json()
    assert {c["key"] for c in cmds} == {"acquire", "followups", "inbox", "approvals", "lifecycle", "insights"}
    assert all(c["examples"] for c in cmds)
    r = client.get("/workflows/route", headers=auth, params={"text": "Follow up with leads who haven't replied"}).json()
    assert r["command"]["key"] == "followups" and "follow up" in r["matched"]
    assert client.get("/workflows/route", headers=auth, params={"text": "make me a sandwich"}).json()["command"] is None


def test_unknown_command_is_refused_with_suggestions(client, auth):
    r = client.post("/workflows/goal", headers=auth, json={"goal": "make me a sandwich"})
    assert r.status_code == 409 and r.json()["error"]["details"]["suggestions"]


def _run(client, auth, goal, **extra):
    wf = client.post("/workflows/goal?run_now=true", headers=auth, json={"goal": goal, **extra})
    assert wf.status_code == 202, wf.text
    return client.get(f"/workflows/{wf.json()['id']}", headers=auth).json()


def test_several_commands_run_independently(client, auth, campaign, lead):
    a = client.post("/workflows/goal", headers=auth, json={"goal": "Find high-quality customers", "campaign_id": campaign["id"]}).json()
    b = client.post("/workflows/goal", headers=auth, json={"goal": "What needs my attention today?"}).json()
    c = client.post("/workflows/goal", headers=auth, json={"goal": "Analyze performance and learn what works"}).json()
    assert len({a["id"], b["id"], c["id"]}) == 3
    assert (a["command"], b["command"], c["command"]) == ("acquire", "approvals", "insights")
    run_once()
    states = {w["command"]: w["state"] for w in client.get("/workflows", headers=auth, params={"workflow_type": "GOAL"}).json()}
    assert states["acquire"] == "AWAITING_APPROVAL" and states["insights"] == "COMPLETED"


def test_acquire_without_campaign_uses_active_campaign(client, auth, campaign, lead):
    wf = _run(client, auth, "Find new customers")
    assert wf["command"] == "acquire" and wf["campaign_id"] == campaign["id"]


def test_approvals_briefing(client, auth, lead):
    client.post(f"/leads/{lead['id']}/process", headers=auth)
    run_once()
    wf = _run(client, auth, "Summarize pending approvals")
    assert wf["state"] == "AWAITING_APPROVAL" and wf["summary"]["pending"] == 1
    assert "Most urgent" in next(e for e in wf["events"] if e["action"] == "Prioritize pending decisions")["result"]


def test_inbox_triage_command(client, auth, lead):
    sent = lead_to_sent(client, auth, lead["id"])
    client.post("/replies", headers=auth, json={"email_id": sent["id"], "body": "Can we set up a call next week?"})
    wf = _run(client, auth, "Triage the inbox")
    assert wf["summary"]["analyzed"] == 1 and wf["summary"]["yellow"] == 1 and wf["state"] == "ESCALATED"
    assert _run(client, auth, "Analyze new replies")["summary"]["analyzed"] == 0


def test_followups_command(client, auth, lead):
    lead_to_sent(client, auth, lead["id"])
    wf = _run(client, auth, "Follow up with leads who haven't replied")
    assert wf["command"] == "followups" and "Next one is due" in wf["events"][-1]["result"]


def test_lifecycle_and_insights_commands(client, auth):
    make_product_and_customer(client, auth)
    wf = _run(client, auth, "Check in with existing customers")
    assert wf["command"] == "lifecycle" and wf["state"] == "COMPLETED"
    wf = _run(client, auth, "Give me a performance report")
    assert wf["command"] == "insights" and any(e["agent"] == "analytics" for e in wf["events"])
