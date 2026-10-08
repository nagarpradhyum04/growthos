"""Customer portal, role-based access, isolation, Product Support AI (RAG), warranty, service, lifecycle."""
from datetime import date, timedelta

from tests.conftest import lead_to_sent, make_product_and_customer, register


def test_customer_cannot_use_owner_api(client, auth):
    _, _, _, portal = make_product_and_customer(client, auth)
    for path in ("/leads", "/campaigns", "/analytics", "/approvals", "/customers", "/agent-runs", "/trace", "/memory"):
        assert client.get(path, headers=portal).status_code == 403, path
    assert client.get("/portal/me", headers=auth).status_code == 403  # and owners can't use the portal API


def test_portal_shows_only_own_products_and_no_internal_data(client, auth):
    product, customer, purchase, portal = make_product_and_customer(client, auth)
    other = client.post("/customers", headers=auth, json={"name": "Other", "email": "o@other.example"}).json()
    other_purchase = client.post(f"/customers/{other['id']}/purchases", headers=auth,
                                 json={"product_id": product["id"], "purchased_at": "2026-01-01"}).json()
    products = client.get("/portal/products", headers=portal).json()
    assert [p["purchase_id"] for p in products] == [purchase["id"]]
    assert products[0]["warranty"]["status"] == "ACTIVE" and products[0]["warranty_expires_at"] == "2028-09-01"
    assert client.get(f"/portal/products/{other_purchase['id']}", headers=portal).status_code == 404
    assert client.post("/portal/warranty", headers=portal,
                       json={"purchase_id": other_purchase["id"], "issue": "Not mine but try"}).status_code == 404
    me = client.get("/portal/me", headers=portal).json()
    assert set(me["customer"]) == {"name", "email", "company", "phone", "preferences"}


def test_other_business_customers_are_isolated(client, auth):
    make_product_and_customer(client, auth)
    other_owner = register(client, "boss@other.example", "Other Org")
    assert client.get("/customers", headers=other_owner).json() == []
    assert client.get("/products", headers=other_owner).json() == []


def test_support_ai_answers_from_documentation_with_sources(client, auth):
    _, _, purchase, portal = make_product_and_customer(client, auth)
    r = client.post("/portal/support/ask", headers=portal,
                    json={"purchase_id": purchase["id"], "question": "How often should I replace the HEPA filter?"}).json()
    assert r["answerable"] is True and "6 months" in r["answer"]["body"]
    assert r["answer"]["sources"][0]["title"] == "AP-500 Manual"
    history = client.get("/portal/support/history", headers=portal, params={"purchase_id": purchase["id"]}).json()
    assert [m["sender"] for m in history] == ["customer", "ai"]


def test_support_ai_says_when_documentation_has_no_answer(client, auth, container):
    _, _, purchase, portal = make_product_and_customer(client, auth)
    calls_before = len(container.llm.run_logger.__dict__)  # noqa: F841 (logger is DB-backed)
    r = client.post("/portal/support/ask", headers=portal,
                    json={"purchase_id": purchase["id"], "question": "Does it support Bluetooth speakers?"}).json()
    assert r["answerable"] is False
    assert r["answer"]["body"] == "I couldn't find that information in the available product documentation."
    assert r["can_escalate"] is True


def test_support_rejects_invented_numbers():
    from app.errors import AgentFailedError
    from app.services.agents.customer_agents import SupportAgent
    from app.services.llm.service import LLMService
    from tests.fakes import ScriptedProvider
    bad = {"answerable": True, "answer": "Replace it every 9 months.", "source_ids": ["S1"], "escalate": False}
    agent = SupportAgent(LLMService(ScriptedProvider(bad, bad), "m", max_transient_retries=0))
    try:
        agent.run(question="filter?", product={}, excerpts=[{"id": "S1", "text": "Replace every 6 months."}])
        raise AssertionError("should fail")
    except AgentFailedError:
        pass


def test_routine_customer_question_is_auto_answered(client, auth):
    _, _, _, portal = make_product_and_customer(client, auth)
    msgs = client.post("/portal/conversations", headers=portal,
                       json={"body": "Hi, what does error code E2 mean?"}).json()
    assert [m["sender"] for m in msgs] == ["customer", "ai"]
    assert "fan is blocked" in msgs[1]["body"]
    assert all("tier" not in m and "intents" not in m for m in msgs)  # nothing internal leaks
    owner_view = client.get("/inbox", headers=auth).json()
    cust = next(m for m in owner_view if m["sender"] == "customer")
    assert cust["tier"] == "GREEN" and cust["handled_automatically"] is True


def test_complaint_is_escalated_red(client, auth):
    _, customer, _, portal = make_product_and_customer(client, auth)
    client.post("/portal/conversations", headers=portal,
                json={"body": "This is unacceptable, the unit broke after a week. I want a refund."})
    approvals = client.get("/approvals", headers=auth).json()
    a = next(a for a in approvals if a["type"] == "MESSAGE_ESCALATION")
    assert a["tier"] == "RED" and a["priority"] == "URGENT" and "refund" in a["reason"]
    assert a["can_automate"] is False
    assert client.post(f"/approvals/{a['id']}/mark-automated", headers=auth, json={}).status_code == 409
    r = client.post(f"/approvals/{a['id']}/approve", headers=auth,
                    json={"response": "I'm sorry to hear that — I'll call you today to sort this out."})
    assert r.json()["status"] == "APPROVED"
    msgs = client.get("/portal/conversations", headers=portal).json()
    assert msgs[-1]["sender"] == "business"


def test_warranty_claim_requires_human_review(client, auth):
    _, _, purchase, portal = make_product_and_customer(client, auth)
    claim = client.post("/portal/warranty", headers=portal,
                        json={"purchase_id": purchase["id"], "issue": "Fan makes a grinding noise."}).json()
    assert claim["status"] == "UNDER_REVIEW"
    owner_claim = client.get("/warranty-claims", headers=auth).json()[0]
    assert owner_claim["eligibility"]["likely_eligible"] is True
    assert owner_claim["eligibility"]["policy_excerpts"], "policy excerpts retrieved for the reviewer"
    a = next(a for a in client.get("/approvals", headers=auth).json() if a["type"] == "WARRANTY_CLAIM")
    assert "require human review" in a["reason"]
    client.post(f"/approvals/{a['id']}/approve", headers=auth, json={"note": "Replacement fan approved"})
    mine = client.get("/portal/warranty", headers=portal).json()[0]
    assert mine["status"] == "APPROVED" and mine["resolution_note"] == "Replacement fan approved"
    assert "eligibility" not in mine


def test_expired_warranty_flagged_but_still_human_decision(client, auth):
    _, _, purchase, portal = make_product_and_customer(client, auth, purchased_at="2023-01-01")
    client.post("/portal/warranty", headers=portal, json={"purchase_id": purchase["id"], "issue": "Stopped working."})
    claim = client.get("/warranty-claims", headers=auth).json()[0]
    assert claim["status"] == "UNDER_REVIEW" and claim["eligibility"]["likely_eligible"] is False


def test_warranty_auto_approve_only_when_configured(client, auth):
    p = client.get("/policy", headers=auth).json()
    p.pop("locked_categories")
    p["warranty_auto_approve"] = True
    client.put("/policy", headers=auth, json=p)
    _, _, purchase, portal = make_product_and_customer(client, auth)
    claim = client.post("/portal/warranty", headers=portal, json={"purchase_id": purchase["id"], "issue": "E1 error."}).json()
    assert claim["status"] == "APPROVED"


def test_service_request_lifecycle(client, auth):
    _, _, purchase, portal = make_product_and_customer(client, auth)
    req = client.post("/portal/service", headers=portal, json={"purchase_id": purchase["id"], "issue": "Annual service",
                                                               "preferred_date": "2026-11-02", "preferred_time": "morning"}).json()
    assert req["status"] == "PENDING_CONFIRMATION"
    bad = client.patch(f"/service-requests/{req['id']}", headers=auth, json={"status": "CONFIRMED"})
    assert bad.status_code == 409  # needs a time
    ok = client.patch(f"/service-requests/{req['id']}", headers=auth,
                      json={"status": "CONFIRMED", "scheduled_for": "2026-11-02T09:00:00Z", "note": "Technician Sam"}).json()
    assert ok["status"] == "CONFIRMED"
    appts = client.get("/portal/appointments", headers=portal).json()
    assert appts[0]["note"] == "Technician Sam"
    for status in ("IN_PROGRESS", "COMPLETED"):
        assert client.patch(f"/service-requests/{req['id']}", headers=auth, json={"status": status}).status_code == 200
    assert client.patch(f"/service-requests/{req['id']}", headers=auth, json={"status": "CANCELLED"}).status_code == 409
    notes = client.get("/portal/notifications", headers=portal).json()
    assert any("completed" in n["title"] for n in notes)


def test_lifecycle_follow_up_sent_once_and_respects_opt_out(client, auth):
    purchased = (date.today() - timedelta(days=8)).isoformat()
    _, customer, _, portal = make_product_and_customer(client, auth, purchased_at=purchased)
    first = client.post("/lifecycle/run", headers=auth).json()
    assert first["sent"] == 1  # max 1 per 7 days
    msgs = client.get("/portal/conversations", headers=portal).json()
    assert msgs and msgs[0]["sender"] == "ai"
    again = client.post("/lifecycle/run", headers=auth).json()
    assert again["sent"] == 0 and again["deferred"] >= 1  # frequency limit defers the second event
    client.patch("/portal/preferences", headers=portal, json={"lifecycle_messages": False})
    _, c2, _, portal2 = make_product_and_customer(client, auth, purchased_at=purchased, email="q@clinic.example")
    client.patch("/portal/preferences", headers=portal2, json={"lifecycle_messages": False})
    out = client.post("/lifecycle/run", headers=auth).json()
    assert out["sent"] == 0
    assert client.get("/portal/conversations", headers=portal2).json() == []


def test_convert_lead_to_customer_carries_memory(client, auth, lead):
    product = client.post("/products", headers=auth, json={"name": "AP-500", "warranty_months": 12}).json()
    lead_to_sent(client, auth, lead["id"])
    c = client.post(f"/leads/{lead['id']}/convert", headers=auth,
                    json={"product_id": product["id"], "order_value": 12000}).json()
    assert c["email"] == "jane@acme-logistics.example" and c["purchases"][0]["product_name"] == "AP-500"
    assert any(m["key"].startswith("lead:") for m in c["memory"])
    assert client.get(f"/leads/{lead['id']}", headers=auth).json()["status"] == "CONVERTED"
    assert client.get("/analytics", headers=auth).json()["overall"]["conversions"] == 1


def test_learning_insights_stored_and_used_by_next_workflow(client, auth, lead):
    lead_to_sent(client, auth, lead["id"])
    out = client.post("/analytics/insights", headers=auth).json()
    assert out["stored_insights"]
    mem = client.get("/memory", headers=auth, params={"scope": "business", "category": "insight"}).json()
    assert mem and mem[0]["source"] == "analytics"
    # A new lead workflow loads those insights for the Outreach Agent.
    from tests.conftest import create_lead
    from app.worker import run_once
    campaign_id = client.get("/campaigns", headers=auth).json()[0]["id"]
    new = create_lead(client, auth, {"id": campaign_id}, email="z@acme3.example", company_name="Acme Three")
    client.post(f"/leads/{new['id']}/process", headers=auth)
    run_once()
    wf = client.get("/workflows", headers=auth, params={"lead_id": new["id"]}).json()[0]
    read = next(e for e in client.get(f"/workflows/{wf['id']}", headers=auth).json()["events"]
                if e["action"].startswith("Load shared memory"))
    assert "learned insight" in read["result"] and read["detail"]["insights"]


def test_forget_me_deletes_lead_memory(client, auth, lead):
    from app.worker import run_once
    client.post(f"/leads/{lead['id']}/process", headers=auth)
    run_once()
    assert client.get("/memory", headers=auth, params={"subject_id": lead["id"]}).json()
    client.post(f"/contacts/{lead['contacts'][0]['id']}/forget", headers=auth)
    assert client.get("/memory", headers=auth, params={"subject_id": lead["id"]}).json() == []
