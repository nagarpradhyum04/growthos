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
    database_url: str = "postgresql+psycopg://postgres:postgres@127.0.0.1:5432/growthos"
    jwt_secret: str = "dev-only-insecure-secret-change-me"
    jwt_expiry_minutes: int = 60 * 12
    public_base_url: str = "http://localhost:8000"
    # Where customers sign in (separate frontend, same API and database).
    portal_url: str = "http://localhost:5174"
    portal_code_ttl_minutes: int = 10
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

    # Social media generation: "gemini" (Nano Banana images + Veo video) or "mock" (offline previews)
    media_provider: str = "mock"
    gemini_api_key: str = ""
    gemini_image_model: str = "gemini-2.5-flash-image"
    gemini_video_model: str = "veo-3.1-generate-preview"
    social_image_aspect: str = "1:1"
    social_video_aspect: str = "9:16"
    media_dir: str = str(REPO_ROOT / "backend" / "media")
    video_timeout_seconds: int = 600
    # Worker queues one image + one video post per org each week (posts still need human approval).
    social_auto_weekly: bool = True

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
    # Parallel job runners in one worker process (commands run side by side).
    worker_concurrency: int = 3

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
