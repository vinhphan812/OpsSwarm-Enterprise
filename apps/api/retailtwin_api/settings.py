"""Process settings. Values come from the environment, never from committed secrets."""

import os
from pathlib import Path
from typing import Literal

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

REPO_ROOT = Path(__file__).resolve().parents[3]
DEFAULT_FIXTURE = REPO_ROOT / "data" / "schemas" / "store-state.example.json"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=REPO_ROOT / ".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # ── Environment ────────────────────────────────────────────────────────────
    app_env: str = Field(default="development")

    # ── Server ────────────────────────────────────────────────────────────────
    api_host: str = Field(default="127.0.0.1")
    api_port: int = Field(default=8000, gt=0, le=65535)

    # ── CORS ─────────────────────────────────────────────────────────────────
    cors_origins: str = Field(default="http://localhost:5173,http://127.0.0.1:5173")

    # ── Store ────────────────────────────────────────────────────────────────
    store_id: str = Field(default="store-001")
    store_fixture_path: Path = Field(default=DEFAULT_FIXTURE)
    # fixture: read-only day-0 fixture, no commits. memory: in-process Live Twin
    # seeded from the fixture. firestore: the Firestore Live Twin (#6).
    live_twin_backend: Literal["fixture", "memory", "firestore"] = Field(default="memory")

    # ── LLM (ADR 0008, ADR 0020) ─────────────────────────────────────────────
    # The day-0 API does not construct a provider. Production construction is
    # checked in retailtwin_api.llm.factory, not at process start.
    llm_provider: str = Field(default="fake")
    llm_model: str = Field(default="fake-test")
    llm_base_url: str | None = None
    llm_api_key: str | None = None
    llm_timeout_seconds: float = Field(default=30.0, gt=0)
    google_cloud_project: str | None = None
    google_cloud_location: str = Field(default="us-central1")

    # ── Autonomy (G03) ───────────────────────────────────────────────────────
    # When true, a new sale.completed accepted by POST /events starts an
    # investigation through the Observer with the configured LLM provider.
    # Off by default so tests and local runs do not call a model per event.
    autonomy_enabled: bool = Field(default=False)

    # ── Logging ──────────────────────────────────────────────────────────────
    log_level: str = Field(default="INFO")

    # ── Autonomous trigger (ADR 0023) ────────────────────────────────────────
    # Off by default in dev so a memory pipe never auto-publishes. Production
    # Cloud Run sets these true so Pub/Sub push drives the agent.
    autonomous_trigger_enabled: bool = Field(default=False)
    autonomous_trigger_interval_seconds: int = Field(default=45, ge=5, le=3600)
    autonomous_scheduled_publisher_enabled: bool = Field(default=False)
    autonomous_pubsub_project: str | None = None
    autonomous_pubsub_subscription: str = Field(default="store-events-agent")
    # In production the ``store-events-agent`` subscription is **push-only**
    # (it points at ``POST /pubsub/agent-events``). Running a background pull
    # loop against the same subscription would flip it back to pull delivery,
    # which Cloud Run cannot do — push and pull are mutually exclusive on one
    # subscription. The pull loop only runs in non-production environments.
    autonomous_pubsub_pull_disabled_in_production: bool = Field(default=True)

    # ── Cloud Run production guard ────────────────────────────────────────────
    # Controls readiness/liveness separation and safety checks.
    # Set to "production" in Cloud Run environment variables.

    # ── Pub/Sub push OIDC audience (ADR 0023) ─────────────────────────────────
    # Cloud Run service URL the Pub/Sub push OIDC token must match. In
    # production the gateway accepts push messages only when the verified
    # ``aud`` claim equals this URL. Empty in dev / test so the route
    # accepts the in-process MemoryPipe path without a real token.
    app_base_url: str = Field(default="")
    # Service-account email the Pub/Sub push OIDC token must be issued for.
    # Pub/Sub's push authenticator is the canonical
    # ``service-<PROJECT_NUMBER>@gcp-sa-pubsub.iam.gserviceaccount.com``
    # service account; in production the route requires the verified
    # ``email`` claim to equal this value AND ``email_verified`` to be true.
    # A different Google-issued ID token for the same audience must NOT be
    # able to invoke the autonomous agent endpoint. Empty in dev / test so
    # the route accepts the in-process MemoryPipe path without a real
    # token; production deployments must set this so the route fails
    # closed on misconfiguration.
    pubsub_push_service_account: str = Field(default="")

    @field_validator("app_env")
    @classmethod
    def validate_app_env(cls, v: str) -> str:
        allowed = {"development", "staging", "production", "test", "e2e-smoke"}
        normalized = v.strip().lower()
        if normalized not in allowed:
            raise ValueError(
                f"APP_ENV must be one of {sorted(allowed)}; got {v!r}. "
                "In Cloud Run set APP_ENV=production."
            )
        return normalized

    @field_validator("log_level")
    @classmethod
    def validate_log_level(cls, v: str) -> str:
        allowed = {"DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"}
        normalized = v.strip().upper()
        if normalized not in allowed:
            raise ValueError(
                f"LOG_LEVEL must be one of {allowed}; got {v!r}."
            )
        return normalized

    @property
    def is_production(self) -> bool:
        return self.app_env == "production"

    @property
    def startup_timeout_seconds(self) -> int:
        """Cloud Run startup probe timeout — must match gcloud --timeout flag."""
        return int(os.environ.get("STARTUP_TIMEOUT_SECONDS", "240"))

    @property
    def readiness_check_timeout_seconds(self) -> int:
        """Single readiness probe HTTP call timeout (must be < startup_timeout_seconds)."""
        return 5


def get_settings() -> Settings:
    return Settings()
