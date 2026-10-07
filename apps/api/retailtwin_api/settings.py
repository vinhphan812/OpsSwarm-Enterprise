"""Process settings. Values come from the environment, never from committed secrets."""

from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

REPO_ROOT = Path(__file__).resolve().parents[3]
DEFAULT_FIXTURE = REPO_ROOT / "data" / "schemas" / "store-state.example.json"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=REPO_ROOT / ".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    app_env: str = "development"
    api_host: str = "127.0.0.1"
    api_port: int = 8000
    cors_origins: str = "http://localhost:5173,http://127.0.0.1:5173"
    store_id: str = "store-001"
    store_fixture_path: Path = Field(default=DEFAULT_FIXTURE)
    log_level: str = "INFO"


def get_settings() -> Settings:
    return Settings()
