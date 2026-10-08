"""Application configuration loaded from environment variables (and an optional .env file)."""
from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

REPO_ROOT = Path(__file__).resolve().parents[2]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=(REPO_ROOT / ".env", ".env"), env_file_encoding="utf-8", extra="ignore"
    )

    # Core
    database_url: str = "postgresql+psycopg://postgres:postgres@localhost:5432/growthos"
    jwt_secret: str = "dev-only-insecure-secret-change-me"
    jwt_expiry_minutes: int = 60 * 12
    public_base_url: str = "http://localhost:8000"
    cors_origins: str = "http://localhost:5173"
    # Shared secret required in the X-Webhook-Secret header of inbound webhooks.
    webhook_secret: str = ""

    # LLM
    llm_provider: str = "mock"
    llm_model: str = ""
    openai_api_key: str = ""
    llm_timeout_seconds: float = 60.0
    llm_max_transient_retries: int = 2
    # Store (redacted) LLM inputs/outputs on agent_runs for debugging.
    log_llm_payloads: bool = True

    # Email
    email_provider: str = "mock"
    email_api_key: str = ""
    email_from_address: str = ""

    # Research
    search_provider: str = "none"
    search_api_key: str = ""
    research_fetch_timeout_seconds: float = 10.0

    # Business rules
    max_followups: int = 2
    followup_delay_days: int = 3
    qualification_threshold: int = 60

    # Worker
    worker_poll_seconds: float = 5.0

    @property
    def cors_origin_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]

    @property
    def resolved_llm_model(self) -> str:
        if self.llm_model:
            return self.llm_model
        return "mock-model" if self.llm_provider == "mock" else "gpt-4o-mini"


@lru_cache
def get_settings() -> Settings:
    return Settings()
