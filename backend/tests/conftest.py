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
