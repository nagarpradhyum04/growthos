"""FastAPI application entry point: `uvicorn app.main:app --reload`."""
import logging

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from sqlalchemy.exc import IntegrityError, OperationalError

from app.api import (
    analytics,
    approvals,
    auth,
    campaigns,
    care,
    contacts,
    customers,
    emails,
    leads,
    memory,
    organization,
    policy,
    portal,
    portal_auth,
    products,
    public,
    replies,
    system,
    webhooks,
    workflows,
)
from app.config import get_settings
from app.errors import GrowthOSError
from app.logging_config import configure_logging

configure_logging()
logger = logging.getLogger("growthos.api")

app = FastAPI(title="GrowthOS API", version="0.1.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=get_settings().cors_origin_list + [get_settings().portal_url],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


def _error(status: int, code: str, message: str, details: dict | None = None) -> JSONResponse:
    return JSONResponse(status_code=status, content={"error": {"code": code, "message": message,
                                                               "details": details or {}}})


@app.exception_handler(GrowthOSError)
def handle_domain_error(request: Request, exc: GrowthOSError):
    return _error(exc.status_code, exc.code, exc.message, exc.details)


@app.exception_handler(RequestValidationError)
def handle_validation_error(request: Request, exc: RequestValidationError):
    details = [{"field": ".".join(str(p) for p in e["loc"][1:]), "message": e["msg"]} for e in exc.errors()]
    return _error(422, "validation_error", "Invalid request", {"fields": details})


@app.exception_handler(IntegrityError)
def handle_integrity_error(request: Request, exc: IntegrityError):
    logger.warning("Integrity error on %s %s: %s", request.method, request.url.path, exc.orig)
    return _error(409, "conflict", "This conflicts with existing data (possibly a duplicate request).")


@app.exception_handler(OperationalError)
def handle_db_error(request: Request, exc: OperationalError):
    logger.error("Database error on %s %s", request.method, request.url.path, exc_info=exc)
    return _error(503, "database_unavailable", "The database is temporarily unavailable. Please retry.")


@app.exception_handler(Exception)
def handle_unexpected(request: Request, exc: Exception):
    # Never leak stack traces to clients; log them internally.
    logger.exception("Unhandled error on %s %s", request.method, request.url.path)
    return _error(500, "internal_error", "Something went wrong. Please try again.")


@app.get("/health", tags=["system"])
def health():
    return {"status": "ok"}


for module in (auth, organization, campaigns, leads, emails, replies, contacts, analytics, system, public, webhooks,
               workflows, approvals, memory, policy, customers, products, care, portal, portal_auth):
    app.include_router(module.router)
