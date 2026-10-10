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
    assert {c["key"] for c in cmds} == {"full_cycle", "acquire", "followups", "inbox", "approvals", "lifecycle", "social", "insights"}
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


def _portal_login(client, business_id, email):
    req = client.post("/portal-auth/request", json={"business_id": business_id, "email": email}).json()
    return client.post("/portal-auth/verify", json={"request_id": req["request_id"], "code": req["dev_code"]})


def test_owner_email_can_also_be_a_portal_customer(client, auth):
    owner_email = client.get("/auth/me", headers=auth).json()["user"]["email"]
    client.post("/customers", headers=auth, json={"name": "Owner as customer", "email": owner_email})
    r = _portal_login(client, _business_id(client, auth), owner_email)
    assert r.status_code == 200, r.text
    portal = {"Authorization": f"Bearer {r.json()['access_token']}"}
    assert client.get("/portal/me", headers=portal).status_code == 200
    # the owner account is unaffected and still signs in with its password
    login = client.post("/auth/login", json={"email": owner_email, "password": "correct-horse-battery"})
    assert login.status_code == 200 and client.get("/auth/me", headers={
        "Authorization": f"Bearer {login.json()['access_token']}"}).status_code == 200


def test_customer_of_two_businesses_signs_in_to_each(client, auth):
    client.post("/customers", headers=auth, json={"name": "Pat", "email": "pat@shared.example"})
    other = register(client, email="owner2@other.example", org="Other Co")
    client.post("/customers", headers=other, json={"name": "Pat", "email": "pat@shared.example"})
    first = _portal_login(client, _business_id(client, auth), "pat@shared.example")
    second = _portal_login(client, _business_id(client, other), "pat@shared.example")
    assert first.status_code == 200 and second.status_code == 200
    me1 = client.get("/portal/me", headers={"Authorization": f"Bearer {first.json()['access_token']}"}).json()
    me2 = client.get("/portal/me", headers={"Authorization": f"Bearer {second.json()['access_token']}"}).json()
    assert me1["business"]["name"] != me2["business"]["name"]
    # signing in again reuses the same portal account
    assert _portal_login(client, _business_id(client, auth), "pat@shared.example").status_code == 200
    # a portal-only email still can't use the owner login
    assert client.post("/auth/login", json={"email": "pat@shared.example", "password": "x" * 12}).status_code == 403
    # owner emails stay unique
    dup = client.post("/auth/register", json={"organization_name": "X", "name": "X", "email": "owner2@other.example",
                                               "password": "correct-horse-battery"})
    assert dup.status_code == 409


def test_unexpected_errors_carry_a_reference(client):
    from app.main import app

    @app.get("/__boom_test")
    def boom():
        raise RuntimeError("boom")

    r = client.get("/__boom_test")
    assert r.status_code == 500 and r.json()["error"]["details"]["ref"] in r.json()["error"]["message"]


def test_full_growth_cycle_runs_every_stage_and_reports_each(client, auth, lead):
    from app.services.command_router import route

    assert route("Run the full growth cycle with all agents").command.key == "full_cycle"
    assert route("run everything").command.key == "full_cycle"
    wf = client.post("/workflows/goal?run_now=true", json={"goal": "Run the full growth cycle with all agents"},
                     headers=auth).json()
    detail = client.get(f"/workflows/{wf['id']}", headers=auth).json()
    stages = [e for e in detail["events"] if e["action"].startswith("Stage: ")]
    assert [e["action"] for e in stages] == [
        "Stage: Find & qualify new customers", "Stage: Triage the inbox", "Stage: Follow up with silent leads",
        "Stage: Check in with existing customers", "Stage: Create this week's social posts",
        "Stage: Analyze performance & learn", "Stage: Brief me on pending decisions"]
    assert all(e["result"] for e in stages)  # every stage says what happened (or why nothing did)
    assert len(detail["children"]) == 7
    # the agents that worked inside sub-workflows are visible to the orchestration view
    agents = {e["agent"] for e in detail["sub_events"]}
    assert {"research", "qualification", "outreach", "safety", "social", "media", "analytics"} <= agents
    assert detail["state"] == "AWAITING_APPROVAL"  # drafts and social posts wait for a human


def test_full_cycle_without_campaign_skips_acquisition_with_a_reason(client):
    headers = register(client, email="solo@biz.example", org="Solo")
    from tests.conftest import BUSINESS_PROFILE

    client.put("/business-profile", json=BUSINESS_PROFILE, headers=headers)
    wf = client.post("/workflows/goal?run_now=true", json={"goal": "run everything"}, headers=headers).json()
    events = client.get(f"/workflows/{wf['id']}", headers=headers).json()["events"]
    skipped = next(e for e in events if e["action"] == "Stage: Find & qualify new customers")
    assert skipped["status"] == "SKIPPED" and "no active campaign" in skipped["result"]


def test_every_draft_reaches_the_approval_center_however_it_was_created(client, auth, lead, db):
    # Manual path (Lead page): research -> qualify -> generate email, no Orchestrator run involved.
    assert client.post(f"/leads/{lead['id']}/research", headers=auth).status_code == 200
    assert client.post(f"/leads/{lead['id']}/qualify", headers=auth).json()["qualified"]
    email = client.post(f"/leads/{lead['id']}/generate-email", headers=auth).json()
    pending = [a for a in client.get("/approvals", headers=auth).json() if a["type"] == "OUTBOUND_EMAIL"]
    assert len(pending) == 1 and pending[0]["subject"]["id"] == email["id"]
    # Regenerating the draft keeps exactly one approval for it.
    client.post(f"/leads/{lead['id']}/generate-email", headers=auth)
    assert len([a for a in client.get("/approvals", headers=auth).json() if a["type"] == "OUTBOUND_EMAIL"]) == 1
    # Approving from the Approval Center sends it through the normal safety path.
    sent = client.post(f"/approvals/{pending[0]['id']}/approve", json={"send": True}, headers=auth)
    assert sent.status_code == 200
    assert client.get(f"/emails/{email['id']}", headers=auth).json()["status"] in ("SENT", "DELIVERED")
    assert not [a for a in client.get("/approvals", headers=auth).json() if a["type"] == "OUTBOUND_EMAIL"]


def test_existing_drafts_without_approval_are_backfilled(client, auth, lead, db):
    from app.models import Approval

    client.post(f"/leads/{lead['id']}/research", headers=auth)
    client.post(f"/leads/{lead['id']}/qualify", headers=auth)
    client.post(f"/leads/{lead['id']}/generate-email", headers=auth)
    db.query(Approval).delete()  # simulate drafts created before this fix
    db.commit()
    assert len(client.get("/approvals", headers=auth).json()) == 1
    assert client.get("/system/status", headers=auth).json()["pending_approvals"] == 1


def test_find_customers_defaults_to_the_campaign_with_new_prospects(client, auth, lead, campaign):
    # The user's case: an older campaign whose only lead was already processed must not be picked
    # over a campaign that still has new prospects.
    client.post(f"/leads/{lead['id']}/research", headers=auth)
    client.post(f"/leads/{lead['id']}/qualify", headers=auth)
    fresh = client.post("/campaigns", headers=auth, json={"name": "Fresh", "objective": "Calls",
                                                          "target_audience": "Sales leaders"}).json()
    done = client.post("/campaigns", headers=auth, json={"name": "Paused Test Campaign", "objective": "x",
                                                         "target_audience": "x"}).json()
    client.post("/leads", headers=auth, json={"campaign_id": fresh["id"], "company_name": "Acme Logistics",
                                              "contact_email": "new@acme-logistics.example", "contact_name": "Jo"})
    camps = {c["name"]: c for c in client.get("/campaigns", headers=auth).json()}
    assert camps["Fresh"]["prospects_waiting"] == 1 and camps["Paused Test Campaign"]["prospects_waiting"] == 0
    wf = client.post("/workflows/goal?run_now=true", headers=auth,
                     json={"goal": "Find high-quality customers for our business"}).json()
    assert wf["campaign_id"] == fresh["id"] and wf["campaign_id"] != done["id"]
    # Running on a campaign with nothing left says where the new prospects are.
    wf2 = client.post("/workflows/goal?run_now=true", headers=auth, json={
        "goal": "Find high-quality customers for our business", "campaign_id": campaign["id"]}).json()
    client.post("/leads", headers=auth, json={"campaign_id": fresh["id"], "company_name": "Beta Freight",
                                              "contact_email": "b@beta-freight.example", "contact_name": "Bo"})
    wf3 = client.post("/workflows/goal?run_now=true", headers=auth, json={
        "goal": "Find high-quality customers for our business", "campaign_id": campaign["id"]}).json()
    finish = [e for e in client.get(f"/workflows/{wf3['id']}", headers=auth).json()["events"] if e["action"] == "Finish"][0]
    assert "Fresh" in finish["result"] and "new prospect" in finish["result"]
    assert wf2


def test_status_bar_reports_the_last_agent_error(client, auth, lead, container):
    from app.services.llm.provider import LLMProviderError
    from tests.fakes import ScriptedProvider

    assert client.get("/system/status", headers=auth).json()["last_agent_run"] is None
    container.llm.provider = ScriptedProvider(LLMProviderError("API key not valid"))
    client.post(f"/leads/{lead['id']}/research", headers=auth)
    last = client.get("/system/status", headers=auth).json()["last_agent_run"]
    assert last["agent"] == "research" and last["status"] != "SUCCEEDED" and "API key not valid" in last["error"]
