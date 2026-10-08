import uuid

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.api.deps import CurrentUser, current_user
from app.db import get_db
from app.models import MemoryEntry
from app.services import memory_service
from app.services.common import get_owned

router = APIRouter(prefix="/memory", tags=["memory"])


class MemoryIn(BaseModel):
    scope: str = Field(pattern="^(business|lead|customer|campaign|product)$")
    subject_id: uuid.UUID | None = None
    category: str = Field(pattern="^(customer_info|preference|product|campaign|conversation|result|research|insight)$")
    key: str = Field(min_length=1, max_length=200)
    content: str = Field(min_length=1, max_length=4000)


def entry_dict(e: MemoryEntry) -> dict:
    return {"id": str(e.id), "scope": e.scope, "subject_id": str(e.subject_id) if e.subject_id else None,
            "category": e.category, "key": e.key, "content": e.content, "data": e.data, "source": e.source,
            "importance": e.importance, "workflow_id": str(e.workflow_id) if e.workflow_id else None,
            "created_at": e.created_at, "updated_at": e.updated_at}


@router.get("")
def list_memory(scope: str | None = None, subject_id: uuid.UUID | None = None, category: str | None = None,
                limit: int = Query(100, le=500), cu: CurrentUser = Depends(current_user), db: Session = Depends(get_db)):
    return [entry_dict(e) for e in memory_service.recall(db, cu.org_id, scope=scope, subject_id=subject_id,
                                                         categories=[category] if category else None, limit=limit)]


@router.post("", status_code=201)
def add_memory(body: MemoryIn, cu: CurrentUser = Depends(current_user), db: Session = Depends(get_db)):
    e = memory_service.remember(db, cu.org_id, scope=body.scope, subject_id=body.subject_id, category=body.category,
                                key=body.key, content=body.content, source="user", importance=2)
    db.commit()
    return entry_dict(e)


@router.delete("/{entry_id}", status_code=204)
def delete_memory(entry_id: uuid.UUID, cu: CurrentUser = Depends(current_user), db: Session = Depends(get_db)):
    db.delete(get_owned(db, MemoryEntry, entry_id, cu.org_id))
    db.commit()
