"""Major API endpoints, authentication and organization isolation."""
import uuid

from app.security import create_unsubscribe_token
from tests.conftest import create_lead, lead_to_sent, register


def test_health(client):
    assert client.get("/health").json() == {"status": "ok"}


def test_register_login_me(client):
    register(client, "a@x.example", "Org A")
    bad = client.post("/auth/login", json={"email": "a@x.example", "password": "wrong-password"})
    assert bad.status_code == 401
    token = client.post("/auth/login", json={"email": "a@x.example", "password": "correct-horse-battery"})
    assert token.status_code == 200
    me = client.get("/auth/me", headers={"Authorization": f"Bearer {token.json()['access_token']}"}).json()
    assert me["user"]["email"] == "a@x.example" and me["organization"]["name"] == "Org A"


def test_duplicate_registration_rejected(client):
    register(client, "a@x.example")
    response = client.post("/auth/register", json={"organization_name": "X", "email": "a@x.example",
                                                   "password": "correct-horse-battery"})
    assert response.status_code == 409


def test_endpoints_require_auth(client):
    for path in ("/leads", "/campaigns", "/emails", "/replies", "/analytics", "/business-profile"):
        assert client.get(path).status_code == 401
    assert client.get("/leads", headers={"Authorization": "Bearer garbage"}).status_code == 401


def test_validation_errors_are_clean(client, auth):
    response = client.post("/leads", headers=auth, json={"company_name": "x"})
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "validation_error"


def test_organizations_are_isolated(client, auth, campaign, lead):
    other = register(client, "intruder@other.example", "Other Org")
    assert client.get("/leads", headers=other).json() == []
    assert client.get("/campaigns", headers=other).json() == []
    assert client.get(f"/leads/{lead['id']}", headers=other).status_code == 404
    assert client.post(f"/leads/{lead['id']}/research", headers=other).status_code == 404
    assert client.post(f"/campaigns/{campaign['id']}/pause", headers=other).status_code == 404
    assert client.post(f"/contacts/{lead['contacts'][0]['id']}/forget", headers=other).status_code == 404
    # Cannot attach a lead to another org's campaign.
    response = client.post("/leads", headers=other, json={"campaign_id": campaign["id"], "company_name": "X",
                                                          "contact_email": "x@y.example"})
    assert response.status_code == 404
    sent = lead_to_sent(client, auth, lead["id"])
    assert client.get(f"/emails/{sent['id']}", headers=other).status_code == 404
    assert client.post(f"/emails/{sent['id']}/send", headers=other).status_code == 404
    assert client.post("/replies", headers=other, json={"email_id": sent["id"], "body": "hi"}).status_code == 404
    assert client.get("/emails", headers=other).json() == []
    assert client.get("/analytics", headers=other).json()["overall"]["leads_total"] == 0


def test_campaign_crud_and_pause_resume(client, auth, campaign):
    listed = client.get("/campaigns", headers=auth).json()
    assert listed[0]["name"] == "Q4 Logistics" and listed[0]["effective_max_followups"] == 2
    assert client.post(f"/campaigns/{campaign['id']}/pause", headers=auth).json()["status"] == "PAUSED"
    assert client.post(f"/campaigns/{campaign['id']}/resume", headers=auth).json()["status"] == "ACTIVE"
    updated = client.put(f"/campaigns/{campaign['id']}", headers=auth,
                         json={"name": "Renamed", "max_followups": 1}).json()
    assert updated["name"] == "Renamed" and updated["effective_max_followups"] == 1


def test_lead_endpoints(client, auth, campaign, lead):
    assert lead["status"] == "NEW" and lead["contacts"][0]["email"] == "jane@acme-logistics.example"
    research = client.post(f"/leads/{lead['id']}/research", headers=auth).json()
    assert research["data"]["industry"] == "Logistics"
    assert research["data"]["evidence_urls"] == ["https://acme-logistics.example"]
    q = client.post(f"/leads/{lead['id']}/qualify", headers=auth).json()
    assert q["qualified"] and q["score"] == 70 and set(q["breakdown"]) >= {"industry_fit", "threshold"}
    email = client.post(f"/leads/{lead['id']}/generate-email", headers=auth).json()
    assert email["status"] == "DRAFT" and "Jane" in email["body"]
    detail = client.get(f"/leads/{lead['id']}", headers=auth).json()
    assert detail["status"] == "DRAFTED" and len(detail["emails"]) == 1
    assert [t["type"] for t in detail["timeline"]][:3] == ["lead_created", "researched", "email_drafted"]
    listed = client.get("/leads", headers=auth, params={"campaign_id": campaign["id"]}).json()
    assert listed[0]["qualification_score"] == 70 and listed[0]["campaign_name"] == "Q4 Logistics"


def test_email_review_shows_research_and_send_check(client, auth, lead):
    client.post(f"/leads/{lead['id']}/research", headers=auth)
    client.post(f"/leads/{lead['id']}/qualify", headers=auth)
    email = client.post(f"/leads/{lead['id']}/generate-email", headers=auth).json()
    review = client.get(f"/emails/{email['id']}", headers=auth).json()
    assert review["research"]["industry"] == "Logistics"
    assert review["personalization_used"]
    assert review["send_check"] == {"allowed": False, "reasons": ["not_approved"]}


def test_regenerating_draft_resets_approval(client, auth, lead):
    client.post(f"/leads/{lead['id']}/research", headers=auth)
    client.post(f"/leads/{lead['id']}/qualify", headers=auth)
    email = client.post(f"/leads/{lead['id']}/generate-email", headers=auth).json()
    client.post(f"/emails/{email['id']}/approve", headers=auth)
    again = client.post(f"/leads/{lead['id']}/generate-email", headers=auth).json()
    assert again["id"] == email["id"] and again["status"] == "DRAFT"


def test_business_profile_required_for_qualification(client, campaign):
    headers = register(client, "new@org.example", "Empty Org")
    camp = client.post("/campaigns", headers=headers, json={"name": "C"}).json()
    lead = create_lead(client, headers, camp)
    client.post(f"/leads/{lead['id']}/research", headers=headers)
    response = client.post(f"/leads/{lead['id']}/qualify", headers=headers)
    assert response.status_code == 409 and "business profile" in response.json()["error"]["message"]


def test_unsubscribe_link_flow(client, auth, lead, email_provider):
    lead_to_sent(client, auth, lead["id"])
    assert "/public/unsubscribe?token=" in email_provider.outbox[0].body
    contact_id = lead["contacts"][0]["id"]
    detail = client.get(f"/leads/{lead['id']}", headers=auth).json()
    token = create_unsubscribe_token(contact_id, detail["campaign"]["id"])  # wrong org -> invalid
    assert "invalid" in client.post(f"/public/unsubscribe?token={token}").text
    token = email_provider.outbox[0].body.split("token=")[1].strip()
    page = client.get(f"/public/unsubscribe?token={token}")  # GET only shows a confirmation
    assert "Unsubscribe me" in page.text
    assert client.get(f"/leads/{lead['id']}", headers=auth).json()["contacts"][0]["suppressed"] is False
    assert "You have been unsubscribed" in client.post(f"/public/unsubscribe?token={token}").text
    contact = client.get(f"/leads/{lead['id']}", headers=auth).json()["contacts"][0]
    assert contact["suppressed"] and contact["unsubscribed"]


def test_inbound_webhook_requires_secret_and_is_idempotent(client, auth, lead):
    sent = lead_to_sent(client, auth, lead["id"])
    org_id = client.get("/auth/me", headers=auth).json()["organization"]["id"]
    payload = {"organization_id": org_id, "from_address": "Jane@acme-logistics.example", "subject": "Re: idea",
               "body": "Interested - can we talk Tuesday?", "message_id": "msg-123"}
    assert client.post("/webhooks/inbound-email", json=payload).status_code == 401
    headers = {"X-Webhook-Secret": "test-webhook-secret"}
    first = client.post("/webhooks/inbound-email", json=payload, headers=headers).json()
    second = client.post("/webhooks/inbound-email", json=payload, headers=headers).json()
    assert first["status"] == "recorded" and second["status"] == "duplicate"
    assert first["reply_id"] == second["reply_id"]
    replies = client.get("/replies", headers=auth).json()
    assert len(replies) == 1 and replies[0]["email_id"] == sent["id"]
    unknown = client.post("/webhooks/inbound-email", headers=headers,
                          json={**payload, "from_address": "stranger@nowhere.example", "message_id": "m2"})
    assert unknown.json()["status"] == "ignored"


def test_delivery_webhook(client, auth, lead, db):
    from app.models import Email

    sent = lead_to_sent(client, auth, lead["id"])
    message_id = db.get(Email, uuid.UUID(sent["id"])).provider_message_id
    headers = {"X-Webhook-Secret": "test-webhook-secret"}
    client.post("/webhooks/email-status", headers=headers, json={"provider_message_id": message_id,
                                                                 "event": "delivered"})
    assert client.get(f"/emails/{sent['id']}", headers=auth).json()["status"] == "DELIVERED"


def test_agent_runs_are_listed(client, auth, lead):
    client.post(f"/leads/{lead['id']}/research", headers=auth)
    runs = client.get("/agent-runs", headers=auth).json()
    assert runs[0]["agent_name"] == "research" and runs[0]["status"] == "SUCCEEDED"
    assert runs[0]["prompt_version"] == "research_v1"


def test_analytics_endpoint(client, auth, lead):
    lead_to_sent(client, auth, lead["id"])
    data = client.get("/analytics", headers=auth).json()
    overall = data["overall"]
    assert overall["leads_total"] == 1 and overall["leads_qualified"] == 1 and overall["emails_sent"] == 1
    assert overall["reply_rate_pct"] == 0.0 and overall["opens"] is None
    assert data["campaigns"][0]["emails_sent"] == 1
    insights = client.post("/analytics/insights", headers=auth).json()
    assert "1 emails were sent" in insights["insights"]["summary"]
