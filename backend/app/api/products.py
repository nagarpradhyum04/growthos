"""Products and the knowledge base (documents chunked for retrieval)."""
import uuid

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.api.deps import CurrentUser, current_user
from app.db import get_db
from app.models import KnowledgeChunk, KnowledgeDocument, Product
from app.services import knowledge_service
from app.services.common import get_owned

router = APIRouter(tags=["products"])


class ProductIn(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    sku: str = Field(default="", max_length=100)
    category: str = Field(default="", max_length=100)
    description: str = Field(default="", max_length=5000)
    warranty_months: int = Field(default=0, ge=0, le=240)
    price: float | None = Field(default=None, ge=0)
    active: bool = True


class DocumentIn(BaseModel):
    title: str = Field(min_length=1, max_length=300)
    doc_type: str = Field(default="manual", pattern="^(manual|faq|warranty_policy|service|policy)$")
    content: str = Field(min_length=1, max_length=200000)
    product_id: uuid.UUID | None = None


class SearchIn(BaseModel):
    query: str = Field(min_length=1, max_length=1000)
    product_id: uuid.UUID | None = None


def product_dict(p: Product) -> dict:
    return {"id": str(p.id), "name": p.name, "sku": p.sku, "category": p.category, "description": p.description,
            "warranty_months": p.warranty_months, "price": float(p.price) if p.price is not None else None,
            "active": p.active}


@router.get("/products")
def list_products(cu: CurrentUser = Depends(current_user), db: Session = Depends(get_db)):
    return [product_dict(p) for p in db.scalars(select(Product).where(Product.organization_id == cu.org_id)
                                                .order_by(Product.name))]


@router.post("/products", status_code=201)
def create_product(body: ProductIn, cu: CurrentUser = Depends(current_user), db: Session = Depends(get_db)):
    p = Product(organization_id=cu.org_id, **body.model_dump())
    db.add(p)
    db.commit()
    return product_dict(p)


@router.put("/products/{product_id}")
def update_product(product_id: uuid.UUID, body: ProductIn, cu: CurrentUser = Depends(current_user),
                   db: Session = Depends(get_db)):
    p = get_owned(db, Product, product_id, cu.org_id)
    for k, v in body.model_dump().items():
        setattr(p, k, v)
    db.commit()
    return product_dict(p)


def doc_dict(d: KnowledgeDocument, chunks: int | None = None) -> dict:
    return {"id": str(d.id), "title": d.title, "doc_type": d.doc_type, "content": d.content,
            "product_id": str(d.product_id) if d.product_id else None, "chunks": chunks, "updated_at": d.updated_at}


@router.get("/knowledge")
def list_documents(cu: CurrentUser = Depends(current_user), db: Session = Depends(get_db)):
    counts = dict(db.execute(select(KnowledgeChunk.document_id, func.count(KnowledgeChunk.id))
                             .where(KnowledgeChunk.organization_id == cu.org_id).group_by(KnowledgeChunk.document_id)).all())
    docs = db.scalars(select(KnowledgeDocument).where(KnowledgeDocument.organization_id == cu.org_id)
                      .order_by(KnowledgeDocument.title))
    return [doc_dict(d, counts.get(d.id, 0)) for d in docs]


@router.post("/knowledge", status_code=201)
def create_document(body: DocumentIn, cu: CurrentUser = Depends(current_user), db: Session = Depends(get_db)):
    if body.product_id:
        get_owned(db, Product, body.product_id, cu.org_id)
    d = knowledge_service.save_document(db, cu.org_id, **body.model_dump())
    db.commit()
    return doc_dict(d)


@router.put("/knowledge/{document_id}")
def update_document(document_id: uuid.UUID, body: DocumentIn, cu: CurrentUser = Depends(current_user),
                    db: Session = Depends(get_db)):
    d = get_owned(db, KnowledgeDocument, document_id, cu.org_id)
    if body.product_id:
        get_owned(db, Product, body.product_id, cu.org_id)
    knowledge_service.save_document(db, cu.org_id, document=d, **body.model_dump())
    db.commit()
    return doc_dict(d)


@router.delete("/knowledge/{document_id}", status_code=204)
def delete_document(document_id: uuid.UUID, cu: CurrentUser = Depends(current_user), db: Session = Depends(get_db)):
    db.delete(get_owned(db, KnowledgeDocument, document_id, cu.org_id))
    db.commit()


@router.post("/knowledge/search")
def search(body: SearchIn, cu: CurrentUser = Depends(current_user), db: Session = Depends(get_db)):
    """Test retrieval: see exactly which excerpts the Support AI would be given."""
    hits = knowledge_service.retrieve(db, cu.org_id, body.query,
                                      product_ids=[body.product_id] if body.product_id else None, k=5)
    return [h.__dict__ for h in hits]
