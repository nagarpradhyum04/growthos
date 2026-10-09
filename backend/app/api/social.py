"""Social Studio: weekly promotional posts (one static image + one short video per week)."""
import uuid
from datetime import date
from pathlib import Path

from fastapi import APIRouter, Depends
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.deps import CurrentUser, container, current_user
from app.db import get_db
from app.errors import NotFoundError
from app.models import SocialPost
from app.models.enums import WorkflowType
from app.services import command_router, jobs, social_service
from app.services import workflow_service as wfs
from app.services.container import Container
from app.services.orchestrator import Orchestrator
from app.services.policy import get_policy

router = APIRouter(prefix="/social", tags=["social"])


class GenerateRequest(BaseModel):
    week_start: date | None = None
    regenerate: bool = False


class PostUpdate(BaseModel):
    caption: str | None = Field(default=None, min_length=1, max_length=5000)
    hashtags: list[str] | None = Field(default=None, max_length=30)
    headline: str | None = Field(default=None, max_length=200)


class Decision(BaseModel):
    note: str = Field(default="", max_length=2000)


def post_dict(p: SocialPost) -> dict:
    return {"id": str(p.id), "week_start": p.week_start, "kind": p.kind, "status": p.status, "theme": p.theme,
            "headline": p.headline, "caption": p.caption, "hashtags": p.hashtags, "platforms": p.platforms,
            "media_prompt": p.media_prompt, "has_media": bool(p.media_path), "media_mime": p.media_mime,
            "media_provider": p.media_provider, "media_model": p.media_model,
            "is_mock_media": p.media_provider == "mock", "policy_notes": p.policy_notes, "error": p.error,
            "agent_run_id": str(p.agent_run_id) if p.agent_run_id else None, "approved_at": p.approved_at,
            "created_at": p.created_at, "updated_at": p.updated_at}


@router.get("/overview")
def overview(cu: CurrentUser = Depends(current_user), db: Session = Depends(get_db),
             c: Container = Depends(container)):
    policy = get_policy(db, cu.org_id)
    provider = c.settings.media_provider
    return {"current_week": social_service.week_start_of(date.today()), "weekly_enabled": policy.social_weekly_enabled,
            "platforms": policy.social_platforms, "media_provider": provider,
            "image_model": c.settings.gemini_image_model if provider == "gemini" else "mock",
            "video_model": c.settings.gemini_video_model if provider == "gemini" else "mock"}


@router.get("/posts")
def list_posts(weeks: int = 8, cu: CurrentUser = Depends(current_user), db: Session = Depends(get_db)):
    posts = db.scalars(select(SocialPost).where(SocialPost.organization_id == cu.org_id)
                       .order_by(SocialPost.week_start.desc(), SocialPost.kind).limit(max(1, min(weeks, 52)) * 2)).all()
    return [post_dict(p) for p in posts]


@router.post("/generate", status_code=202)
def generate(body: GenerateRequest, run_now: bool = False, cu: CurrentUser = Depends(current_user),
             db: Session = Depends(get_db), c: Container = Depends(container)):
    """Runs through the Orchestrator's 'social' command, so it shows up in the Command Center and trace."""
    week = social_service.week_start_of(body.week_start or date.today())
    from app.services.common import business_profile_context

    business_profile_context(db, cu.org_id)  # fail fast with a clear message if the profile is missing
    wf = wfs.start_workflow(db, cu.org_id, WorkflowType.GOAL, goal=f"Create social posts · week of {week}",
                            plan=list(command_router.BY_KEY["social"].plan), command="social")
    db.commit()
    options = {"week_start": str(week), "regenerate": body.regenerate}
    if run_now:
        Orchestrator(db, c).run_command(wf, options=options)
    else:
        jobs.enqueue(db, "run_goal", {"workflow_id": str(wf.id), "options": options}, organization_id=cu.org_id,
                     dedupe_key=f"goal:{wf.id}")
        db.commit()
    return {"workflow_id": str(wf.id), "week_start": week}


@router.patch("/posts/{post_id}")
def update_post(post_id: uuid.UUID, body: PostUpdate, cu: CurrentUser = Depends(current_user),
                db: Session = Depends(get_db)):
    post = social_service.get_post(db, cu.org_id, post_id)
    social_service.update_post(db, post, caption=body.caption, hashtags=body.hashtags, headline=body.headline,
                               banned_phrases=get_policy(db, cu.org_id).banned_phrases)
    db.commit()
    return post_dict(post)


@router.post("/posts/{post_id}/regenerate-media")
def regenerate_media(post_id: uuid.UUID, cu: CurrentUser = Depends(current_user), db: Session = Depends(get_db),
                     c: Container = Depends(container)):
    post = social_service.get_post(db, cu.org_id, post_id)
    return post_dict(social_service.regenerate_media(db, c, post))


@router.post("/posts/{post_id}/approve")
def approve(post_id: uuid.UUID, body: Decision, cu: CurrentUser = Depends(current_user), db: Session = Depends(get_db)):
    post = social_service.get_post(db, cu.org_id, post_id)
    social_service.decide(db, post, approve=True, user_id=cu.id, note=body.note or "Approved for publishing")
    db.commit()
    return post_dict(post)


@router.post("/posts/{post_id}/reject")
def reject(post_id: uuid.UUID, body: Decision, cu: CurrentUser = Depends(current_user), db: Session = Depends(get_db)):
    post = social_service.get_post(db, cu.org_id, post_id)
    social_service.decide(db, post, approve=False, user_id=cu.id, note=body.note or "Rejected")
    db.commit()
    return post_dict(post)


@router.get("/posts/{post_id}/media")
def media(post_id: uuid.UUID, cu: CurrentUser = Depends(current_user), db: Session = Depends(get_db),
          c: Container = Depends(container)):
    post = social_service.get_post(db, cu.org_id, post_id)
    if not post.media_path:
        raise NotFoundError("This post has no media yet")
    base = Path(c.settings.media_dir).resolve()
    path = (base / Path(post.media_path).name).resolve()
    if path.parent != base or not path.is_file():
        raise NotFoundError("Media file not found")
    ext = path.suffix.lstrip(".")
    return FileResponse(path, media_type=post.media_mime or "application/octet-stream",
                        filename=f"growthos-{post.kind}-{post.week_start}.{ext}")
