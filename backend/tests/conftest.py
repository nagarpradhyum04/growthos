"""Test fixtures. Tests run against a real PostgreSQL database (TEST_DATABASE_URL)."""
import os

os.environ["DATABASE_URL"] = os.environ.get(
    "TEST_DATABASE_URL", "postgresql+psycopg://postgres:postgres@localhost:5432/growthos_test"
)
os.environ.setdefault("JWT_SECRET", "test-secret-test-secret-test-secret")
os.environ["LLM_PROVIDER"] = "mock"
os.environ["EMAIL_PROVIDER"] = "mock"
os.environ["SEARCH_PROVIDER"] = "none"
os.environ["WEBHOOK_SECRET"] = "test-webhook-secret"
os.environ["MAX_FOLLOWUPS"] = "2"
os.environ["FOLLOWUP_DELAY_DAYS"] = "3"
os.environ["QUALIFICATION_THRESHOLD"] = "60"

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402
from sqlalchemy import text  # noqa: E402

from app.config import get_settings  # noqa: E402
from app.db import SessionLocal, engine  # noqa: E402
from app.models import Base  # noqa: E402
from app.services.container import Container, set_container  # noqa: E402
from app.services.email.mock_provider import MockEmailProvider  # noqa: E402
from app.services.llm.mock_provider import MockLLMProvider  # noqa: E402
from app.services.llm.run_logger import DbRunLogger  # noqa: E402
from app.services.llm.service import LLMService  # noqa: E402
from app.services.search import EvidenceDoc, StaticResearchTools  # noqa: E402

ACME_EVIDENCE = [
    EvidenceDoc(
        url="https://acme-logistics.example",
        title="Acme Logistics",
        text=(
            "Acme Logistics is a freight and logistics software platform for mid-size shippers. "
            "We have 120 employees across two offices. We are hiring 5 account executives to grow our sales team. "
            "Acme launched a new real-time routing product in March."
        ),
        source_type="website",
    )
]

BUSINESS_PROFILE = {
    "company_name": "PipelinePro",
    "company_description": "PipelinePro builds outbound sales pipelines for B2B companies.",
    "products_services": "Done-for-you outbound prospecting and account executive onboarding for sales teams",
    "target_customers": "B2B software and logistics companies with growing sales teams",
    "value_proposition": "We help growing sales teams onboard new account executives and fill their pipeline faster",
    "industries": ["Logistics", "Software"],
    "target_company_sizes": ["50-500"],
    "tone": "friendly, concise",
    "website": "https://pipelinepro.example",
    "key_differentiators": "Specialized in logistics tech",
    "campaign_goals": "Book discovery calls",
    "sender_name": "Sam from PipelinePro",
}


@pytest.fixture(scope="session", autouse=True)
def _schema():
    Base.metadata.drop_all(engine)
    Base.metadata.create_all(engine)
    yield


@pytest.fixture(autouse=True)
def _clean_db():
    tables = ", ".join(t.name for t in reversed(Base.metadata.sorted_tables))
    with engine.begin() as conn:
        conn.execute(text(f"TRUNCATE {tables} RESTART IDENTITY CASCADE"))
    yield


@pytest.fixture
def email_provider() -> MockEmailProvider:
    return MockEmailProvider()


@pytest.fixture
def research_tools():
    return StaticResearchTools(ACME_EVIDENCE)


@pytest.fixture
def container(email_provider, research_tools) -> Container:
    settings = get_settings()
    c = Container(
        settings=settings,
        llm=LLMService(MockLLMProvider(), "mock-model", run_logger=DbRunLogger(SessionLocal),
                       max_transient_retries=0),
        research_tools=research_tools,
        email_provider=email_provider,
    )
    set_container(c)
    yield c
    set_container(None)


@pytest.fixture
def db():
    session = SessionLocal()
    yield session
    session.close()


@pytest.fixture
def client(container) -> TestClient:
    from app.main import app

    return TestClient(app, raise_server_exceptions=False)


def register(client: TestClient, email: str = "owner@pipelinepro.example", org: str = "PipelinePro") -> dict:
    response = client.post("/auth/register", json={"organization_name": org, "name": "Owner", "email": email,
                                                   "password": "correct-horse-battery"})
    assert response.status_code == 201, response.text
    return {"Authorization": f"Bearer {response.json()['access_token']}"}


@pytest.fixture
def auth(client) -> dict:
    headers = register(client)
    assert client.put("/business-profile", json=BUSINESS_PROFILE, headers=headers).status_code == 200
    return headers


@pytest.fixture
def campaign(client, auth) -> dict:
    response = client.post("/campaigns", json={"name": "Q4 Logistics", "objective": "Book discovery calls",
                                               "target_audience": "Sales leaders at logistics software companies"},
                           headers=auth)
    assert response.status_code == 201, response.text
    return response.json()


def create_lead(client, auth, campaign, email="jane@acme-logistics.example", **overrides) -> dict:
    body = {"campaign_id": campaign["id"], "company_name": "Acme Logistics",
            "website": "https://acme-logistics.example", "contact_name": "Jane Doe",
            "contact_role": "VP Sales", "contact_email": email, **overrides}
    response = client.post("/leads", json=body, headers=auth)
    assert response.status_code == 201, response.text
    return response.json()


@pytest.fixture
def lead(client, auth, campaign) -> dict:
    return create_lead(client, auth, campaign)


def lead_to_sent(client, auth, lead_id: str) -> dict:
    """Run the human-in-the-loop flow up to a sent initial email. Returns the email."""
    assert client.post(f"/leads/{lead_id}/research", headers=auth).status_code == 200
    q = client.post(f"/leads/{lead_id}/qualify", headers=auth)
    assert q.status_code == 200 and q.json()["qualified"], q.text
    email = client.post(f"/leads/{lead_id}/generate-email", headers=auth).json()
    assert client.post(f"/emails/{email['id']}/approve", headers=auth).status_code == 200
    sent = client.post(f"/emails/{email['id']}/send", headers=auth)
    assert sent.status_code == 200, sent.text
    return sent.json()


MANUAL = """# Setup
Place the AP-500 on a flat surface at least 30 cm from walls. Remove the plastic wrap from the HEPA filter before first use.

# Filter replacement
Replace the HEPA filter every 6 months. The filter indicator turns red when replacement is due. Clean the pre-filter monthly with a vacuum.

# Error codes
E1 means the filter is not seated correctly. E2 means the fan is blocked; switch off and remove obstructions.
"""
WARRANTY = """# Coverage
The AP-500 is covered for 24 months from the purchase date against manufacturing defects.

# Exclusions
Physical damage, water damage and use of non-original filters are not covered.
"""


def make_product_and_customer(client, auth, purchased_at="2026-09-01", email="pat@clinic.example"):
    product = client.post("/products", headers=auth, json={"name": "AP-500 Air Purifier", "sku": "AP500",
                                                           "category": "Air purifier", "warranty_months": 24,
                                                           "description": "Commercial HEPA air purifier"}).json()
    client.post("/knowledge", headers=auth, json={"title": "AP-500 Manual", "doc_type": "manual", "content": MANUAL,
                                                  "product_id": product["id"]})
    client.post("/knowledge", headers=auth, json={"title": "Warranty policy", "doc_type": "warranty_policy",
                                                  "content": WARRANTY, "product_id": product["id"]})
    customer = client.post("/customers", headers=auth, json={"name": "Pat Lee", "email": email,
                                                             "company": "Northside Clinic"}).json()
    purchase = client.post(f"/customers/{customer['id']}/purchases", headers=auth,
                           json={"product_id": product["id"], "purchased_at": purchased_at,
                                 "serial_number": "SN-1001", "order_value": 4000}).json()
    portal = portal_login(client, auth, email)
    return product, customer, purchase, portal


def portal_login(client, auth, email: str) -> dict:
    """Customer portal sign-in: Business ID + email -> Access Agent -> one-time code (shown in mock mode)."""
    business_id = client.get("/auth/me", headers=auth).json()["organization"]["business_code"]
    req = client.post("/portal-auth/request", json={"business_id": business_id, "email": email}).json()
    assert "dev_code" in req, req
    token = client.post("/portal-auth/verify", json={"request_id": req["request_id"], "code": req["dev_code"]}).json()
    return {"Authorization": f"Bearer {token['access_token']}"}
