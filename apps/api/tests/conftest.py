import pytest
from fastapi.testclient import TestClient

from retailtwin_api.main import create_app
from retailtwin_api.settings import DEFAULT_FIXTURE, Settings

_SETTINGS_ENV = (
    "APP_ENV",
    "API_HOST",
    "API_PORT",
    "CORS_ORIGINS",
    "STORE_ID",
    "STORE_FIXTURE_PATH",
    "LOG_LEVEL",
)


@pytest.fixture
def settings(monkeypatch: pytest.MonkeyPatch) -> Settings:
    for key in _SETTINGS_ENV:
        monkeypatch.delenv(key, raising=False)
    return Settings(
        _env_file=None,
        app_env="test",
        store_id="store-001",
        store_fixture_path=DEFAULT_FIXTURE,
    )


@pytest.fixture
def client(settings: Settings):
    application = create_app(settings)
    with TestClient(application) as test_client:
        yield test_client
