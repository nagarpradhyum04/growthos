"""Weekly social media promotion: one static image post + one short video post per week.

Pipeline (one SOCIAL workflow per run, visible in the agent trace):
  Social Content Agent (theme, captions, hashtags, visual/video prompts — business facts only)
  -> Safety Agent (deterministic policy checks: banned phrases, platform limits, claim checks)
  -> media provider (Nano Banana image, Veo video; or the clearly-labelled mock)
  -> human approval. Nothing is ever published automatically.
"""
import logging
import re
import uuid
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.errors import AgentFailedError, InvalidStateError
from app.models import BusinessProfile, Organization, Product, SocialPost, Workflow
from app.models.enums import ApprovalStatus, ApprovalType, Priority, TraceStatus, WorkflowState, WorkflowType
from app.services import approval_service, jobs, memory_service
from app.services import workflow_service as wfs
from app.services.common import business_profile_context, get_owned
from app.services.container import Container
from app.services.llm.run_logger import RunContext
from app.services.media import MediaError
from app.services.policy import get_policy

logger = logging.getLogger(__name__)

KINDS = ("image", "video")
FINAL = ("APPROVED", "REJECTED")
# Hard caption limits per platform (characters) and hashtag guidance.
PLATFORM_CAPTION_LIMITS = {"instagram": 2200, "facebook": 63206, "linkedin": 3000, "x": 280, "tiktok": 2200}
_EXT = {"image/png": "png", "image/jpeg": "jpg", "image/webp": "webp", "image/svg+xml": "svg",
        "video/mp4": "mp4", "video/webm": "webm"}


def week_start_of(d: date) -> date:
    return d - timedelta(days=d.weekday())


def media_dir(container: Container) -> Path:
    path = Path(container.settings.media_dir)
    path.mkdir(parents=True, exist_ok=True)
    return path


def policy_findings(text: str, hashtags: list[str], platforms: list[str], banned_phrases: list[str]) -> list[str]:
    """Deterministic checks a human should see before approving. Any finding -> NEEDS_REVIEW."""
    notes = []
    lowered = text.lower()
    for phrase in banned_phrases or []:
        if phrase and re.search(r"\b" + re.escape(phrase.lower()) + r"\b", lowered):
            notes.append(f"Contains banned phrase “{phrase}” (Settings & Rules)")
    full = f"{text}\n\n{' '.join(hashtags)}".strip()
    for p in platforms:
        limit = PLATFORM_CAPTION_LIMITS.get(p)
        if limit and len(full) > limit:
            notes.append(f"Caption + hashtags is {len(full)} characters; {p} allows {limit}")
    if "instagram" in platforms and len(hashtags) > 30:
        notes.append("Instagram allows at most 30 hashtags")
    return notes


def _products(db: Session, organization_id) -> list[dict]:
    rows = db.scalars(select(Product).where(Product.organization_id == organization_id, Product.active.is_(True))
                      .order_by(Product.created_at).limit(20)).all()
    out = []
    for p in rows:
        item = {"name": p.name, "category": p.category, "description": p.description}
        if p.price is not None:
            item["price"] = str(p.price)
        out.append(item)
    return out


def _previous_themes(db: Session, organization_id, before: date) -> list[str]:
    rows = db.scalars(select(SocialPost.theme).where(SocialPost.organization_id == organization_id,
                                                     SocialPost.week_start < before, SocialPost.theme != "")
                      .order_by(SocialPost.week_start.desc()).limit(12)).all()
    return list(dict.fromkeys(rows))[:6]


def _get_or_create(db: Session, organization_id, week: date, kind: str) -> SocialPost:
    post = db.scalar(select(SocialPost).where(SocialPost.organization_id == organization_id,
                                              SocialPost.week_start == week, SocialPost.kind == kind))
    if post is None:
        post = SocialPost(organization_id=organization_id, week_start=week, kind=kind, status="GENERATING",
                          hashtags=[], platforms=[], policy_notes=[])
        db.add(post)
        try:
            db.flush()
        except IntegrityError:  # created concurrently by another runner
            db.rollback()
            post = db.scalar(select(SocialPost).where(SocialPost.organization_id == organization_id,
                                                      SocialPost.week_start == week, SocialPost.kind == kind))
    return post


def _store_media(container: Container, post: SocialPost, data: bytes, mime: str) -> None:
    ext = _EXT.get(mime, "bin")
    directory = media_dir(container)
    for old in directory.glob(f"{post.id}*"):
        old.unlink(missing_ok=True)
    # A fresh name per render so caches (and updated_at) change when the media is regenerated.
    path = directory / f"{post.id}-{uuid.uuid4().hex[:8]}.{ext}"
    path.write_bytes(data)
    post.media_path = path.name  # relative to MEDIA_DIR; never a client-supplied path
    post.media_mime = mime


def _render_media(db: Session, container: Container, wf: Workflow, post: SocialPost, company: str) -> bool:
    s = container.settings
    action = "Generate image (Nano Banana)" if post.kind == "image" else "Generate video (Veo)"
    if s.media_provider != "gemini":
        action = "Generate image preview (mock)" if post.kind == "image" else "Generate video storyboard (mock)"
    started = wfs.now()
    try:
        provider = container.media()
        brand = {"company": company, "headline": post.headline}
        if post.kind == "image":
            result = provider.generate_image(post.media_prompt, aspect_ratio=s.social_image_aspect, brand=brand)
        else:
            result = provider.generate_video(post.media_prompt, aspect_ratio=s.social_video_aspect, brand=brand)
    except MediaError as exc:
        post.status = "FAILED"
        post.error = str(exc)[:1000]
        wfs.record(db, wf, "media", action, TraceStatus.FAILED, str(exc)[:500], started_at=started)
        return False
    _store_media(container, post, result.data, result.mime)
    post.media_provider, post.media_model, post.error = result.provider, result.model, None
    wfs.record(db, wf, "media", action, TraceStatus.COMPLETED,
               f"{post.kind.title()} created with {result.model} ({len(result.data) / 1024:.1f} KB, {result.mime})",
               started_at=started, detail={"provider": result.provider, "model": result.model})
    return True


def _request_approval(db: Session, post: SocialPost) -> None:
    flagged = post.status == "NEEDS_REVIEW"
    approval_service.create(
        db, post.organization_id, ApprovalType.SOCIAL_POST,
        title=f"Weekly {post.kind} post · {post.theme}",
        reason=("Policy checks flagged this post: " + "; ".join(post.policy_notes)) if flagged else
        "Social posts are never published automatically. Review the caption and media, then approve.",
        priority=Priority.HIGH if flagged else Priority.MEDIUM, category="social",
        recommended_action="Fix the flagged items, then approve" if flagged else "Approve and publish to your page",
        suggested_response=post.caption, social_post_id=post.id)


def generate_week(db: Session, container: Container, organization_id: uuid.UUID, *, week: date | None = None,
                  regenerate: bool = False, wf: Workflow | None = None) -> dict:
    """Create (or recreate) this week's image + video posts. Approved/rejected posts are never overwritten."""
    week = week_start_of(week or date.today())
    profile = business_profile_context(db, organization_id)  # raises if the profile isn't set up
    policy = get_policy(db, organization_id)
    platforms = list(policy.social_platforms or [])
    if wf is None:
        wf = wfs.start_workflow(db, organization_id, WorkflowType.GOAL, goal=f"Weekly social posts · week of {week}",
                                command="social", plan=["social_content", "safety", "media", "human_review"])
        db.commit()

    posts = {k: _get_or_create(db, organization_id, week, k) for k in KINDS}
    todo = [k for k, p in posts.items() if p.status not in FINAL and (regenerate or p.status in ("GENERATING", "FAILED"))]
    if not todo:
        wfs.record(db, wf, "orchestrator", "Check this week's posts", TraceStatus.SKIPPED,
                   f"Posts for the week of {week} already exist; nothing to generate", state=WorkflowState.COMPLETED)
        wf.summary = {"week_start": str(week), "generated": 0}
        db.commit()
        return wf.summary
    for k in todo:
        posts[k].status = "GENERATING"
    db.commit()

    context = {"business_profile": profile, "products": _products(db, organization_id), "week_start": str(week),
               "platforms": platforms, "previous_themes": _previous_themes(db, organization_id, week)}
    try:
        with wfs.step(db, wf, "social", "Plan theme & write posts", state=WorkflowState.DRAFTING) as st:
            r = container.social_agent().run(context, RunContext(organization_id=organization_id))
            st.agent_run_id = r.run_id
            st.result = f"Theme “{r.output.theme}”: image post + video post written from your business profile"
    except AgentFailedError as exc:
        for k in todo:
            posts[k].status, posts[k].error = "FAILED", exc.message
        wfs.set_state(wf, WorkflowState.FAILED, exc.message)
        db.commit()
        return {"week_start": str(week), "generated": 0, "error": exc.message}
    out = r.output

    wfs.set_state(wf, WorkflowState.SAFETY_CHECK)
    texts = {"image": (out.image_post.caption, out.image_post.hashtags, out.image_post.visual_prompt,
                       out.image_post.headline),
             "video": (out.video_post.caption, out.video_post.hashtags, out.video_post.video_prompt, out.theme[:200])}
    flagged = 0
    for k in todo:
        caption, tags, prompt, headline = texts[k]
        p = posts[k]
        p.theme, p.caption, p.hashtags, p.media_prompt, p.headline = out.theme, caption, tags, prompt, headline
        p.platforms, p.agent_run_id, p.error = platforms, r.run_id, None
        p.policy_notes = policy_findings(f"{headline}\n{caption}", tags, platforms, policy.banned_phrases)
        flagged += bool(p.policy_notes)
    wfs.record(db, wf, "safety", "Check posts against your rules", TraceStatus.COMPLETED if not flagged else TraceStatus.WAITING,
               "No issues: banned phrases, platform limits and claims checked" if not flagged else
               f"{flagged} post(s) flagged for review: " + "; ".join(n for k in todo for n in posts[k].policy_notes))
    db.commit()

    wfs.set_state(wf, WorkflowState.DRAFTING)
    company = profile.get("company_name") or ""
    ready = 0
    for k in todo:
        p = posts[k]
        if _render_media(db, container, wf, p, company):
            p.status = "NEEDS_REVIEW" if p.policy_notes else "READY"
            _request_approval(db, p)
            ready += 1
        db.commit()

    memory_service.remember(db, organization_id, scope="business", subject_id=None, category="social",
                            key=f"social:{week}", content=f"Weekly social theme for {week}: {out.theme}", source="social")
    if ready:
        wfs.record(db, wf, "human", "Route posts to business owner", TraceStatus.WAITING,
                   f"{ready} post(s) waiting for your approval in Social Studio — nothing is published automatically",
                   state=WorkflowState.AWAITING_APPROVAL)
    else:
        wfs.set_state(wf, WorkflowState.FAILED, "Media generation failed; see the trace")
    wf.summary = {"week_start": str(week), "theme": out.theme, "generated": ready, "flagged": flagged,
                  "failed": len(todo) - ready}
    db.commit()
    return wf.summary


def regenerate_media(db: Session, container: Container, post: SocialPost) -> SocialPost:
    if post.status in FINAL:
        raise InvalidStateError(f"Post is {post.status.lower()}; it can't be changed")
    if not post.media_prompt:
        raise InvalidStateError("This post has no media prompt yet; generate the week first")
    company = db.scalar(select(BusinessProfile.company_name).where(BusinessProfile.organization_id == post.organization_id)) or ""
    wf = wfs.start_workflow(db, post.organization_id, WorkflowType.GOAL, command="social",
                            goal=f"Regenerate {post.kind} for week of {post.week_start}", plan=["media", "human_review"])
    if _render_media(db, container, wf, post, company):
        post.status = "NEEDS_REVIEW" if post.policy_notes else "READY"
        _request_approval(db, post)
        wfs.record(db, wf, "human", "Route post to business owner", TraceStatus.WAITING,
                   "Waiting for your approval", state=WorkflowState.AWAITING_APPROVAL)
    else:
        wfs.set_state(wf, WorkflowState.FAILED, post.error)
    db.commit()
    return post


def update_post(db: Session, post: SocialPost, *, caption: str | None, hashtags: list[str] | None,
                headline: str | None, banned_phrases: list[str]) -> SocialPost:
    if post.status in FINAL:
        raise InvalidStateError(f"Post is {post.status.lower()}; it can't be edited")
    if caption is not None:
        post.caption = caption.strip()
    if hashtags is not None:
        post.hashtags = [t if t.startswith("#") else f"#{t}" for t in (h.strip() for h in hashtags) if t]
    if headline is not None:
        post.headline = headline.strip()[:200]
    post.policy_notes = policy_findings(f"{post.headline}\n{post.caption}", post.hashtags, post.platforms, banned_phrases)
    if post.media_path:
        post.status = "NEEDS_REVIEW" if post.policy_notes else "READY"
    db.flush()
    return post


def decide(db: Session, post: SocialPost, *, approve: bool, user_id, note: str | None = None) -> SocialPost:
    if post.status in FINAL:
        raise InvalidStateError(f"Post is already {post.status.lower()}")
    if approve:
        if not post.media_path:
            raise InvalidStateError("Generate the media before approving")
        if post.policy_notes:
            raise InvalidStateError("Fix the flagged items first: " + "; ".join(post.policy_notes))
    post.status = "APPROVED" if approve else "REJECTED"
    post.approved_by_user_id = user_id if approve else None
    post.approved_at = datetime.now(timezone.utc) if approve else None
    approval_service.resolve_for(db, status=ApprovalStatus.APPROVED if approve else ApprovalStatus.REJECTED,
                                 user_id=user_id, note=note, social_post_id=post.id)
    memory_service.remember(db, post.organization_id, scope="business", subject_id=None, category="social",
                            key=f"social:{post.week_start}:{post.kind}:decision",
                            content=f"{post.kind.title()} post “{post.theme}” was {post.status.lower()} by the owner",
                            source="human")
    db.flush()
    return post


def schedule_weekly(db: Session, today: date | None = None) -> int:
    """Worker hook: queue this week's generation for every org that has it switched on and a profile set up.
    Idempotent: one job per org per week (dedupe key) and existing posts are never regenerated."""
    week = week_start_of(today or date.today())
    queued = 0
    for org_id in db.scalars(select(Organization.id)).all():
        if not get_policy(db, org_id).social_weekly_enabled:
            continue
        profile = db.scalar(select(BusinessProfile).where(BusinessProfile.organization_id == org_id))
        if profile is None or not (profile.company_description or profile.products_services):
            continue
        if db.scalar(select(SocialPost.id).where(SocialPost.organization_id == org_id, SocialPost.week_start == week)):
            continue
        dedupe = f"social:{org_id}:{week}"
        from app.models import Job

        if db.scalar(select(Job.id).where(Job.dedupe_key == dedupe)):
            continue  # already ran (or failed) for this week; the owner can retry from Social Studio
        jobs.enqueue(db, "generate_social_week", {"week_start": str(week)}, organization_id=org_id, dedupe_key=dedupe,
                     max_attempts=1)
        queued += 1
    db.commit()
    return queued


def get_post(db: Session, organization_id, post_id: uuid.UUID) -> SocialPost:
    return get_owned(db, SocialPost, post_id, organization_id)
