"""Orchestrator workflows, state transitions, agent trace and shared memory."""
from app.errors import AgentFailedError
from app.services.llm.provider import LLMTimeoutError
from app.worker import run_once
from tests.conftest import create_lead
from tests.fakes import ScriptedProvider


def _trace(client, auth, wf_id):
    return client.get(f"/workflows/{wf_id}", headers=auth).json()


def test_goal_workflow_plans_fans_out_and_waits_for_humans(client, auth, campaign, research_tools):
    create_lead(client, auth, campaign)
    create_lead(client, auth, campaign, email="ops@acme2.example", company_name="Acme Two")
    wf = client.post("/workflows/goal", headers=auth, json={"goal": "Find high-quality customers for our business",
                                                            "campaign_id": campaign["id"]}).json()
    assert wf["type"] == "GOAL" and wf["state"] == "PENDING"
    run_once()
    detail = _trace(client, auth, wf["id"])
    assert detail["state"] == "AWAITING_APPROVAL"
    assert detail["summary"]["researched"] == 2 and detail["summary"]["drafted"] == 2
    agents = [e["agent"] for e in detail["events"]]
    for agent in ("orchestrator", "memory", "research", "qualification", "outreach", "safety", "human"):
        assert agent in agents
    assert len(detail["children"]) == 2 and all(c["state"] == "AWAITING_APPROVAL" for c in detail["children"])
    approvals = client.get("/approvals", headers=auth).json()
    assert len(approvals) == 2 and all(a["type"] == "OUTBOUND_EMAIL" for a in approvals)
    assert all(a["reason"].startswith("Escalated because") for a in approvals)


def test_lead_workflow_state_transitions_across_send_and_reply(client, auth, lead):
    client.post(f"/leads/{lead['id']}/process", headers=auth)
    run_once()
    wf = client.get("/workflows", headers=auth, params={"lead_id": lead["id"]}).json()[0]
    assert wf["state"] == "AWAITING_APPROVAL"
    approval = client.get("/approvals", headers=auth).json()[0]
    r = client.post(f"/approvals/{approval['id']}/approve", headers=auth, json={"send": True})
    assert r.status_code == 200 and r.json()["status"] == "APPROVED"
    assert _trace(client, auth, wf["id"])["state"] == "WAITING_FOR_REPLY"
    email = client.get(f"/leads/{lead['id']}", headers=auth).json()["emails"][0]
    client.post("/replies?analyze_now=true", headers=auth,
                json={"email_id": email["id"], "body": "Sounds great, can we set up a call next week?"})
    detail = _trace(client, auth, wf["id"])
    assert detail["state"] == "ESCALATED"
    states = [e["state_after"] for e in detail["events"]]
    for s in ("RESEARCHING", "QUALIFYING", "DRAFTING", "SAFETY_CHECK", "AWAITING_APPROVAL", "READY_TO_SEND",
              "SENT", "WAITING_FOR_REPLY", "REPLY_RECEIVED", "ESCALATED"):
        assert s in states, s


def test_disqualified_lead_completes_without_outreach(client, auth, campaign, research_tools):
    research_tools._documents = []
    lead = create_lead(client, auth, campaign, email="x@none.example", company_name="Nothing Co", website="")
    client.post(f"/leads/{lead['id']}/process", headers=auth)
    run_once()
    wf = client.get("/workflows", headers=auth, params={"lead_id": lead["id"]}).json()[0]
    detail = _trace(client, auth, wf["id"])
    assert detail["state"] == "COMPLETED"
    assert "No outreach will be written" in detail["events"][-1]["result"]
    assert client.get("/approvals", headers=auth).json() == []


def test_research_facts_written_to_shared_memory_and_read_back(client, auth, lead):
    client.post(f"/leads/{lead['id']}/process", headers=auth)
    run_once()
    mem = client.get("/memory", headers=auth, params={"scope": "lead", "subject_id": lead["id"]}).json()
    keys = {m["key"] for m in mem}
    assert {"industry", "company_size", "signals", "qualification"} <= keys
    assert all(m["source"] in ("research", "qualification") for m in mem)
    wf = client.get("/workflows", headers=auth, params={"lead_id": lead["id"]}).json()[0]
    reads = [e for e in _trace(client, auth, wf["id"])["events"] if e["action"].startswith("Load shared memory")]
    assert reads and "lead fact" in reads[0]["result"]


def test_transient_failure_is_retried_once(client, auth, lead, container):
    good = container.llm.provider
    research_out = good.complete_json  # keep mock for later steps

    class Flaky:
        name = "flaky"
        calls = 0

        def complete_json(self, req):
            Flaky.calls += 1
            if req.agent_name == "research" and Flaky.calls == 1:
                raise LLMTimeoutError("timeout")
            return research_out(req)

    container.llm.provider = Flaky()
    client.post(f"/leads/{lead['id']}/process", headers=auth)
    run_once()
    wf = client.get("/workflows", headers=auth, params={"lead_id": lead["id"]}).json()[0]
    statuses = [(e["agent"], e["status"]) for e in _trace(client, auth, wf["id"])["events"]]
    assert ("research", "RETRYING") in statuses and ("research", "COMPLETED") in statuses
    assert wf["state"] == "AWAITING_APPROVAL"


def test_invalid_output_fails_workflow_without_retry_loop(client, auth, lead, container):
    container.llm.provider = ScriptedProvider("bad", "bad")
    client.post(f"/leads/{lead['id']}/process", headers=auth)
    run_once()
    wf = client.get("/workflows", headers=auth, params={"lead_id": lead["id"]}).json()[0]
    assert wf["state"] == "FAILED"
    assert any(e["status"] == "FAILED" for e in _trace(client, auth, wf["id"])["events"])
    assert AgentFailedError  # imported for clarity


def test_trace_feed_lists_recent_events(client, auth, lead):
    client.post(f"/leads/{lead['id']}/process", headers=auth)
    run_once()
    feed = client.get("/trace", headers=auth).json()
    assert feed and {"agent", "action", "status", "result", "started_at", "duration_ms"} <= feed[0].keys()
