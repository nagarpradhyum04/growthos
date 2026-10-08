"""Knowledge base + retrieval for grounded answers (RAG).

Retrieval is lexical BM25 over paragraph chunks stored in Postgres: deterministic, offline and good
enough for product manuals/FAQs at MVP scale. The interface (`retrieve`) is the seam where an
embedding-based retriever (e.g. pgvector) can be swapped in later without touching the agents.
"""
import math
import re
import uuid
from collections import Counter
from dataclasses import dataclass

from sqlalchemy import delete, or_, select
from sqlalchemy.orm import Session

from app.models import KnowledgeChunk, KnowledgeDocument

_TOKEN = re.compile(r"[a-z0-9]+")
_STOP = {
    "the", "a", "an", "and", "or", "of", "to", "in", "on", "for", "is", "are", "it", "my", "i", "do", "does",
    "how", "what", "when", "can", "you", "your", "with", "be", "this", "that", "should", "will", "if", "at", "me",
}
MAX_CHUNK = 700


def tokens(text: str) -> list[str]:
    out = []
    for t in _TOKEN.findall(text.lower()):
        if t in _STOP:
            continue
        if len(t) > 4 and t.endswith("s"):
            t = t[:-1]  # crude plural folding: filters -> filter
        out.append(t)
    return out


def chunk_text(content: str) -> list[tuple[str, str]]:
    """Split into (heading, text) chunks on blank lines / markdown headings, max ~700 chars."""
    chunks: list[tuple[str, str]] = []
    heading, buf = "", ""
    for block in re.split(r"\n\s*\n", content.strip()):
        block = block.strip()
        if not block:
            continue
        if block.startswith("#"):
            first, _, rest = block.partition("\n")
            if buf:
                chunks.append((heading, buf.strip()))
                buf = ""
            heading = first.lstrip("#").strip()
            block = rest.strip()
            if not block:
                continue
        if len(buf) + len(block) > MAX_CHUNK and buf:
            chunks.append((heading, buf.strip()))
            buf = ""
        buf += block + "\n\n"
    if buf.strip():
        chunks.append((heading, buf.strip()))
    return chunks


def save_document(db: Session, organization_id: uuid.UUID, *, title: str, content: str, doc_type: str,
                  product_id=None, document: KnowledgeDocument | None = None) -> KnowledgeDocument:
    doc = document or KnowledgeDocument(organization_id=organization_id)
    doc.title, doc.content, doc.doc_type, doc.product_id = title, content, doc_type, product_id
    if document is None:
        db.add(doc)
    db.flush()
    db.execute(delete(KnowledgeChunk).where(KnowledgeChunk.document_id == doc.id))
    for i, (heading, text) in enumerate(chunk_text(content)):
        db.add(KnowledgeChunk(organization_id=organization_id, document_id=doc.id, product_id=product_id,
                              position=i, heading=heading, text=text))
    db.flush()
    return doc


@dataclass
class Retrieved:
    chunk_id: str
    document_id: str
    title: str
    heading: str
    doc_type: str
    text: str
    score: float


def retrieve(db: Session, organization_id: uuid.UUID, query: str, *, product_ids: list | None = None,
             doc_types: list[str] | None = None, k: int = 4, min_score: float = 0.5) -> list[Retrieved]:
    """BM25 over the org's chunks. product_ids restricts to those products + general (product-less) docs."""
    stmt = (select(KnowledgeChunk, KnowledgeDocument)
            .join(KnowledgeDocument, KnowledgeDocument.id == KnowledgeChunk.document_id)
            .where(KnowledgeChunk.organization_id == organization_id))
    if product_ids is not None:
        stmt = stmt.where(or_(KnowledgeChunk.product_id.in_(product_ids), KnowledgeChunk.product_id.is_(None)))
    if doc_types:
        stmt = stmt.where(KnowledgeDocument.doc_type.in_(doc_types))
    rows = db.execute(stmt).all()
    q = set(tokens(query))
    if not rows or not q:
        return []
    docs = [(c, d, tokens(f"{d.title} {c.heading} {c.text}")) for c, d in rows]
    n = len(docs)
    avg = sum(len(t) for _, _, t in docs) / n
    df = Counter(term for _, _, t in docs for term in set(t))
    scored = []
    for c, d, toks in docs:
        tf = Counter(toks)
        score = 0.0
        for term in q:
            if term not in tf:
                continue
            idf = math.log(1 + (n - df[term] + 0.5) / (df[term] + 0.5))
            score += idf * tf[term] * 2.2 / (tf[term] + 1.2 * (0.25 + 0.75 * len(toks) / avg))
        if score >= min_score:
            scored.append(Retrieved(str(c.id), str(d.id), d.title, c.heading, d.doc_type, c.text, round(score, 3)))
    return sorted(scored, key=lambda r: r.score, reverse=True)[:k]
