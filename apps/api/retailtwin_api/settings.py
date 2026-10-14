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

    # ── Logging ──────────────────────────────────────────────────────────────
    log_level: str = Field(default="INFO")

    # ── Cloud Run production guard ────────────────────────────────────────────
    # Controls readiness/liveness separation and safety checks.
    # Set to "production" in Cloud Run environment variables.
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
