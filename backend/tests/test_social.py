"""Weekly social posts: Social Content Agent, media providers (Nano Banana / Veo), safety, human approval."""
import base64
import json
from datetime import date

import httpx
import pytest

from app.config import get_settings
from app.errors import AgentFailedError
from app.services.agents.customer_agents import SocialContentAgent, social_claim_problems
from app.services.llm.service import LLMService
from app.services.media import MediaError
from app.services.media.gemini import GeminiMediaProvider
from app.services.social_service import policy_findings, schedule_weekly, week_start_of
from tests.conftest import BUSINESS_PROFILE
from tests.fakes import ScriptedProvider

GOOD = {
    "theme": "Faster AE onboarding",
    "image_post": {"headline": "Onboard reps faster", "caption": "PipelinePro helps growing sales teams onboard new "
                   "account executives and fill their pipeline faster. Learn more at https://pipelinepro.example.",
                   "hashtags": ["#Sales", "B2B"], "visual_prompt": "Editorial photo of a modern sales floor, soft light."},
    "video_post": {"caption": "A quick look at how PipelinePro fills pipelines for logistics tech sales teams. "
                   "Message us to learn more.", "hashtags": ["#Logistics"],
                   "video_prompt": "Scene 1: a sales team at work. Scene 2: a pipeline board filling up."},
}


def _agent(*payloads) -> SocialContentAgent:
    return SocialContentAgent(LLMService(ScriptedProvider(*payloads), "test-model", max_transient_retries=0))


def test_week_start_is_monday():
    assert week_start_of(date(2026, 10, 9)) == date(2026, 10, 5)
    assert week_start_of(date(2026, 10, 5)) == date(2026, 10, 5)


def test_agent_accepts_grounded_posts_and_normalizes_hashtags():
    out = _agent(GOOD).run({"business_profile": BUSINESS_PROFILE, "products": []}).output
    assert out.image_post.hashtags == ["#Sales", "#B2B"]


def test_agent_rejects_invented_offers_and_numbers():
    bad = json.loads(json.dumps(GOOD))
    bad["image_post"]["caption"] = "Get 50% off this week only! We have helped 300 teams. Visit pipelinepro.example now."
    with pytest.raises(AgentFailedError):
        _agent(bad, bad).run({"business_profile": BUSINESS_PROFILE, "products": []})


def test_claim_checks_allow_facts_the_business_gave():
    assert social_claim_problems("Free setup for teams of 50-500", "free setup, teams of 50-500") == []
    assert social_claim_problems("Guaranteed results", "we build pipelines")


def test_policy_findings_flag_banned_phrases_and_platform_limits():
    notes = policy_findings("Act now, " + "x" * 300, ["#a"], ["x"], ["act now"])
    assert any("banned phrase" in n for n in notes) and any("x allows 280" in n for n in notes)
    assert policy_findings("A calm, factual caption.", ["#a"], ["instagram"], ["act now"]) == []


def test_gemini_image_parses_inline_data():
    png = b"\x89PNG fake"
    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["url"], seen["key"] = str(request.url), request.headers.get("x-goog-api-key")
        seen["body"] = json.loads(request.content)
        return httpx.Response(200, json={"candidates": [{"content": {"parts": [
            {"text": "here"}, {"inlineData": {"mimeType": "image/png", "data": base64.b64encode(png).decode()}}]}}]})

    settings = get_settings().model_copy(update={"gemini_api_key": "k-test", "media_provider": "gemini"})
    res = GeminiMediaProvider(settings, transport=httpx.MockTransport(handler)).generate_image(
        "a poster", aspect_ratio="1:1", brand={})
    assert res.data == png and res.mime == "image/png" and res.model == settings.gemini_image_model
    assert seen["url"].endswith(f"models/{settings.gemini_image_model}:generateContent") and seen["key"] == "k-test"
    assert seen["body"]["generationConfig"]["responseModalities"] == ["IMAGE"]


def test_gemini_video_polls_operation_then_downloads():
    calls = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request.method + " " + request.url.path)
        if request.url.path.endswith(":predictLongRunning"):
            return httpx.Response(200, json={"name": "models/veo/operations/op1", "done": False})
        if request.url.path.endswith("operations/op1"):
            return httpx.Response(200, json={"name": "op1", "done": True, "response": {"generateVideoResponse": {
                "generatedSamples": [{"video": {"uri": "https://files.example/v1/video.mp4"}}]}}})
        return httpx.Response(200, content=b"MP4DATA", headers={"content-type": "video/mp4"})

    settings = get_settings().model_copy(update={"gemini_api_key": "k-test"})
    res = GeminiMediaProvider(settings, transport=httpx.MockTransport(handler), poll_seconds=0).generate_video(
        "Scene 1", aspect_ratio="9:16", brand={})
    assert res.data == b"MP4DATA" and res.mime == "video/mp4" and len(calls) == 3


def test_gemini_errors_become_media_errors():
    settings = get_settings().model_copy(update={"gemini_api_key": "k-test"})
    provider = GeminiMediaProvider(settings, transport=httpx.MockTransport(
        lambda r: httpx.Response(200, json={"promptFeedback": {"blockReason": "SAFETY"}})))
    with pytest.raises(MediaError, match="SAFETY"):
        provider.generate_image("x", aspect_ratio="1:1", brand={})
    with pytest.raises(MediaError, match="GEMINI_API_KEY"):
        GeminiMediaProvider(get_settings().model_copy(update={"gemini_api_key": None}))


def _generate(client, auth) -> list[dict]:
    r = client.post("/social/generate?run_now=true", json={}, headers=auth)
    assert r.status_code == 202, r.text
    return client.get("/social/posts", headers=auth).json()


def test_weekly_generation_creates_one_image_and_one_video_awaiting_approval(client, auth):
    posts = _generate(client, auth)
    assert sorted(p["kind"] for p in posts) == ["image", "video"]
    assert all(p["status"] == "READY" and p["has_media"] and p["is_mock_media"] for p in posts)
    assert {p["week_start"] for p in posts} == {str(week_start_of(date.today()))}
    # media is served only to the owner
    image = next(p for p in posts if p["kind"] == "image")
    media = client.get(f"/social/posts/{image['id']}/media", headers=auth)
    assert media.status_code == 200 and media.headers["content-type"].startswith("image/svg+xml")
    assert b"MOCK PREVIEW" in media.content
    assert client.get(f"/social/posts/{image['id']}/media").status_code == 401
    # each post waits in the Human Approval Center; nothing is published
    approvals = [a for a in client.get("/approvals", headers=auth).json() if a["type"] == "SOCIAL_POST"]
    assert len(approvals) == 2 and all(a["subject"]["kind"] == "social_post" for a in approvals)
    # the run is a normal Orchestrator command with a visible trace
    trace = client.get("/trace", headers=auth).json()
    assert {"social", "safety", "media", "human"} <= {e["agent"] for e in trace}
    # running again the same week does not duplicate
    assert len(_generate(client, auth)) == 2


def test_other_business_cannot_see_or_approve_posts(client, auth):
    from tests.conftest import register

    posts = _generate(client, auth)
    other = register(client, email="owner@other.example", org="Other")
    assert client.get("/social/posts", headers=other).json() == []
    assert client.post(f"/social/posts/{posts[0]['id']}/approve", json={}, headers=other).status_code == 404
    assert client.get(f"/social/posts/{posts[0]['id']}/media", headers=other).status_code == 404


def test_flagged_post_must_be_fixed_before_approval(client, auth):
    posts = _generate(client, auth)
    post = posts[0]
    r = client.patch(f"/social/posts/{post['id']}", json={"caption": "Act now, this is a limited time offer for you."},
                     headers=auth)
    assert r.json()["status"] == "NEEDS_REVIEW" and r.json()["policy_notes"]
    assert client.post(f"/social/posts/{post['id']}/approve", json={}, headers=auth).status_code == 409
    fixed = client.patch(f"/social/posts/{post['id']}", json={"caption": "A clear, factual caption about our service."},
                         headers=auth).json()
    assert fixed["status"] == "READY"
    approved = client.post(f"/social/posts/{post['id']}/approve", json={}, headers=auth).json()
    assert approved["status"] == "APPROVED"
    assert client.patch(f"/social/posts/{post['id']}", json={"caption": "Changed after approval"},
                        headers=auth).status_code == 409
    pending = [a for a in client.get("/approvals", headers=auth).json() if a["type"] == "SOCIAL_POST"]
    assert len(pending) == 1  # the approved post's approval was closed


def test_approval_center_approves_social_post(client, auth):
    _generate(client, auth)
    a = next(a for a in client.get("/approvals", headers=auth).json() if a["type"] == "SOCIAL_POST")
    assert client.post(f"/approvals/{a['id']}/approve", json={}, headers=auth).status_code == 200
    post = next(p for p in client.get("/social/posts", headers=auth).json() if p["id"] == a["subject"]["id"])
    assert post["status"] == "APPROVED"


def test_regenerate_week_keeps_approved_posts(client, auth):
    posts = _generate(client, auth)
    image = next(p for p in posts if p["kind"] == "image")
    client.post(f"/social/posts/{image['id']}/approve", json={}, headers=auth)
    client.post("/social/generate?run_now=true", json={"regenerate": True}, headers=auth)
    after = {p["id"]: p for p in client.get("/social/posts", headers=auth).json()}
    assert after[image["id"]]["status"] == "APPROVED" and after[image["id"]]["caption"] == image["caption"]


def test_generation_requires_business_profile(client):
    from tests.conftest import register

    headers = register(client, email="new@biz.example", org="NewBiz")
    r = client.post("/social/generate?run_now=true", json={}, headers=headers)
    assert r.status_code == 409 and "business profile" in r.json()["error"]["message"].lower()


def test_command_router_maps_social_commands():
    from app.services.command_router import route

    assert route("Create this week's social media posts").command.key == "social"
    assert route("make an instagram promo video").command.key == "social"


def test_weekly_scheduler_queues_once_per_org_and_respects_switch(client, auth, db):
    from app.worker import run_once

    assert schedule_weekly(db) == 1
    assert schedule_weekly(db) == 0  # deduped for this week
    run_once()
    assert len(client.get("/social/posts", headers=auth).json()) == 2
    policy = client.get("/policy", headers=auth).json()
    assert policy["social_weekly_enabled"] is True
    policy["social_weekly_enabled"] = False
    assert client.put("/policy", json=policy, headers=auth).status_code == 200
    assert schedule_weekly(db, date.today().replace(year=date.today().year + 1)) == 0


def test_media_failure_is_reported_not_faked(client, auth, container):
    class Broken:
        name = "gemini"

        def generate_image(self, *a, **k):
            raise MediaError("quota exceeded")

        generate_video = generate_image

    container.media_provider = Broken()
    posts = _generate(client, auth)
    assert all(p["status"] == "FAILED" and not p["has_media"] and "quota" in p["error"] for p in posts)
    assert not [a for a in client.get("/approvals", headers=auth).json() if a["type"] == "SOCIAL_POST"]


def test_system_status_counts_real_state(client, auth):
    before = client.get("/system/status", headers=auth).json()
    assert before["workflows_running"] == 0 and before["pending_approvals"] == 0
    assert before["providers"] == {"llm": "mock", "email": "mock", "media": "mock"}
    _generate(client, auth)
    after = client.get("/system/status", headers=auth).json()
    assert after["pending_approvals"] == 2
    assert {"social", "media"} <= set(after["agents_active_10m"])
    assert after["memory_entries"] >= 1
