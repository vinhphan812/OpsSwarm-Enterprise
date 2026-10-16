"""Tests for the Pub/Sub push endpoint ``POST /pubsub/agent-events``.

The endpoint receives Pub/Sub HTTP push envelopes from the
``store-events-agent`` subscription. We exercise it with synthetic
envelopes and an in-memory observer world (MemoryPipe +
MemoryActivationLedger + recording starter).
"""

from __future__ import annotations

import base64
from datetime import datetime, timezone
from typing import Any

import pytest
from fastapi.testclient import TestClient

from retailtwin_api.agents.observer.consumer import (
    InvestigationStart,
    MemoryActivationLedger,
)
from retailtwin_api.backbone import (
    BackboneError,
    EventPipe,
    MemoryPipe,
    MemoryQuarantine as _BackboneMemoryQuarantine,
    PulledMessage,
)
from retailtwin_api.main import create_app
from retailtwin_api.flagship.agent_starter import FlagshipInvestigationStarter
from retailtwin_api.schemas import StoreEvent
from retailtwin_api.settings import DEFAULT_FIXTURE, Settings


# ---------------------------------------------------------------------------
# Test doubles
# ---------------------------------------------------------------------------


class _RecordingStarter:
    def __init__(self) -> None:
        self.starts: list[InvestigationStart] = []

    def start_investigation_for_event(self, start: InvestigationStart) -> None:
        self.starts.append(start)

    def start_investigation(self, start: InvestigationStart) -> None:
        self.starts.append(start)


def _canonical_body(event_id: str = "evt-push-1") -> str:
    payload = {
        "correlation_id": "run-canonical-push",
        "event_id": event_id,
        "event_type": "sale.completed",
        "store_id": "store-001",
        "sku": "P017",
        "quantity": 1,
        "occurred_at": "2026-10-15T12:00:00Z",
        "source": "synthetic-pos",
    }
    import json as _json

    return _json.dumps(payload, separators=(",", ":"), sort_keys=True)


def _envelope(body: str, message_id: str = "msg-1") -> dict[str, Any]:
    return {
        "subscription": "projects/retailtwin-ai-511002/subscriptions/store-events-agent",
        "message": {
            "data": base64.b64encode(body.encode("utf-8")).decode("utf-8"),
            "messageId": message_id,
            "attributes": {
                "correlation_id": "run-canonical-push",
                "event_id": "evt-push-1",
                "event_type": "sale.completed",
                "store_id": "store-001",
            },
        },
    }


def _settings() -> Settings:
    return Settings(
        _env_file=None,
        app_env="test",
        store_id="store-001",
        store_fixture_path=DEFAULT_FIXTURE,
    )


def _wire_observer(app: Any, starter: _RecordingStarter) -> MemoryPipe:
    pipe = MemoryPipe()
    ledger = MemoryActivationLedger()
    quarantine = _BackboneMemoryQuarantine()
    flags_starter = FlagshipInvestigationStarter(controller_getter=lambda: None)
    app.state.event_pipe = pipe
    app.state.activation_ledger = ledger
    app.state.observer_quarantine = quarantine
    app.state.observer_starter = flags_starter
    return pipe


# ---------------------------------------------------------------------------
# Envelope decoding helper
# ---------------------------------------------------------------------------


def test_decode_envelope_round_trips_body_and_attributes() -> None:
    from retailtwin_api.routes import _decode_pubsub_push_envelope

    body = _canonical_body()
    message_id, attributes, ack_id = _decode_pubsub_push_envelope(_envelope(body, "msg-42"))
    assert message_id == body  # body round-trips through base64
    assert attributes == {
        "correlation_id": "run-canonical-push",
        "event_id": "evt-push-1",
        "event_type": "sale.completed",
        "store_id": "store-001",
    }
    assert ack_id == "msg-42"


def test_decode_envelope_rejects_missing_message() -> None:
    from retailtwin_api.routes import _decode_pubsub_push_envelope

    with pytest.raises(Exception) as exc_info:  # ApiError 400
        _decode_pubsub_push_envelope({"subscription": "x"})
    assert "missing 'message'" in str(exc_info.value)


def test_decode_envelope_rejects_non_base64_data() -> None:
    from retailtwin_api.routes import _decode_pubsub_push_envelope

    with pytest.raises(Exception) as exc_info:
        _decode_pubsub_push_envelope(
            {
                "subscription": "x",
                "message": {"data": "***not-base64***"},
            }
        )
    assert "base64" in str(exc_info.value)


def test_decode_envelope_rejects_non_mapping_message() -> None:
    from retailtwin_api.routes import _decode_pubsub_push_envelope

    with pytest.raises(Exception) as exc_info:
        _decode_pubsub_push_envelope({"message": "not-a-mapping"})
    assert "must be an object" in str(exc_info.value)


def test_decode_envelope_rejects_missing_data() -> None:
    from retailtwin_api.routes import _decode_pubsub_push_envelope

    with pytest.raises(Exception) as exc_info:
        _decode_pubsub_push_envelope({"message": {"attributes": {}}})
    assert "missing 'data'" in str(exc_info.value)


def test_decode_envelope_rejects_non_mapping_attributes() -> None:
    from retailtwin_api.routes import _decode_pubsub_push_envelope

    payload = base64.b64encode(b"{}").decode("utf-8")
    with pytest.raises(Exception) as exc_info:
        _decode_pubsub_push_envelope(
            {"message": {"data": payload, "attributes": "not-a-mapping"}}
        )
    assert "must be an object" in str(exc_info.value)


def test_decode_envelope_uses_subscription_as_ack_id_when_message_id_missing() -> None:
    from retailtwin_api.routes import _decode_pubsub_push_envelope

    payload = base64.b64encode(b"{}").decode("utf-8")
    _, _, ack_id = _decode_pubsub_push_envelope(
        {
            "subscription": "projects/p/subscriptions/store-events-agent",
            "message": {"data": payload, "attributes": {}},
        }
    )
    assert ack_id == "projects/p/subscriptions/store-events-agent"


# ---------------------------------------------------------------------------
# Endpoint integration
# ---------------------------------------------------------------------------


def test_pubsub_route_starts_an_investigation_and_returns_200() -> None:
    settings = _settings()
    app = create_app(settings)
    starter = _RecordingStarter()
    pipe = _wire_observer(app, starter)
    with TestClient(app) as client:
        # The lifespan already populated app.state.observer_starter;
        # override with our recording stub so we don't run the real chain.
        app.state.observer_starter = starter  # type: ignore[assignment]
        response = client.post("/pubsub/agent-events", json=_envelope(_canonical_body()))
    assert response.status_code == 200
    payload = response.json()
    assert payload["outcome"] == "started"
    assert payload["event_id"] == "evt-push-1"
    assert payload["correlation_id"] == "run-canonical-push"
    assert starter.starts and starter.starts[0].event.event_id == "evt-push-1"
    # The consumer acks the message; the in-process MemoryPipe has no acks
    # record for the push envelope, but the observation moved forward.
    assert pipe.acked == []


def test_pubsub_route_returns_500_when_observation_fails() -> None:
    class _FailingStarter:
        def start_investigation_for_event(self, start: InvestigationStart) -> None:
            raise RuntimeError("boom")

        def start_investigation(self, start: InvestigationStart) -> None:
            raise RuntimeError("boom")

    settings = _settings()
    app = create_app(settings)
    pipe = _wire_observer(app, _RecordingStarter())
    with TestClient(app) as client:
        app.state.observer_starter = _FailingStarter()  # type: ignore[assignment]
        response = client.post("/pubsub/agent-events", json=_envelope(_canonical_body()))
    assert response.status_code == 500
    assert response.json()["error"]["code"] == "observation_failed"


def test_pubsub_route_quarantines_invalid_event_with_200() -> None:
    settings = _settings()
    app = create_app(settings)
    starter = _RecordingStarter()
    pipe = _wire_observer(app, starter)
    # Inject an invalid JSON body — consumer will quarantine and return 200.
    envelope = _envelope("not-json")
    with TestClient(app) as client:
        app.state.observer_starter = starter  # type: ignore[assignment]
        response = client.post("/pubsub/agent-events", json=envelope)
    assert response.status_code == 200
    payload = response.json()
    assert payload["outcome"] == "rejected"
    assert payload["event_id"] is None


def test_pubsub_route_returns_503_when_observer_not_wired() -> None:
    settings = _settings()
    app = create_app(settings)
    with TestClient(app) as client:
        # The lifespan wires observer_starter, so we strip it here to
        # verify the route's defensive 503 path.
        app.state.observer_starter = None  # type: ignore[assignment]
        response = client.post("/pubsub/agent-events", json=_envelope(_canonical_body()))
    assert response.status_code == 503
    assert response.json()["error"]["code"] == "observer_unavailable"


# ---------------------------------------------------------------------------
# OIDC bearer token verification (P0-4)
# ---------------------------------------------------------------------------


def _production_settings(**overrides: object) -> Settings:
    return Settings(
        _env_file=None,
        app_env="production",
        store_id="store-001",
        store_fixture_path=DEFAULT_FIXTURE,
        app_base_url="https://retailtwin-api-511002.run.app",
        pubsub_push_service_account="service-537192856637@gcp-sa-pubsub.iam.gserviceaccount.com",
        **overrides,  # type: ignore[arg-type]
    )


def test_pubsub_route_in_production_requires_authorization_header() -> None:
    """Missing Authorization header is a 401 in production."""

    settings = _production_settings()
    app = create_app(settings)
    starter = _RecordingStarter()
    with TestClient(app) as client:
        app.state.observer_starter = starter  # type: ignore[assignment]
        response = client.post(
            "/pubsub/agent-events",
            json=_envelope(_canonical_body()),
        )
    assert response.status_code == 401
    assert response.json()["error"]["code"] == "pubsub_auth_missing"
    assert starter.starts == []


def test_pubsub_route_in_production_rejects_malformed_bearer() -> None:
    """A non-Bearer (or empty) Authorization header is a 401."""

    settings = _production_settings()
    app = create_app(settings)
    starter = _RecordingStarter()
    with TestClient(app) as client:
        app.state.observer_starter = starter  # type: ignore[assignment]
        response = client.post(
            "/pubsub/agent-events",
            json=_envelope(_canonical_body()),
            headers={"authorization": "Token abc.def.ghi"},
        )
    assert response.status_code == 401
    assert response.json()["error"]["code"] == "pubsub_auth_malformed"
    assert starter.starts == []


def test_pubsub_route_in_production_rejects_unsigned_token(monkeypatch: pytest.MonkeyPatch) -> None:
    """A bearer token with an invalid signature is rejected with 401."""

    from retailtwin_api import routes

    settings = _production_settings()
    app = create_app(settings)
    starter = _RecordingStarter()
    monkeypatch.setattr(
        "google.oauth2.id_token.verify_oauth2_token",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(ValueError("bad signature")),
    )
    with TestClient(app) as client:
        app.state.observer_starter = starter  # type: ignore[assignment]
        response = client.post(
            "/pubsub/agent-events",
            json=_envelope(_canonical_body()),
            headers={"authorization": "Bearer fake.token.value"},
        )
    assert response.status_code == 401
    assert response.json()["error"]["code"] == "pubsub_auth_invalid"
    assert starter.starts == []


def test_pubsub_route_in_production_rejects_wrong_audience(monkeypatch: pytest.MonkeyPatch) -> None:
    """A token whose ``aud`` does not match ``app_base_url`` is rejected with 401."""

    settings = _production_settings()
    app = create_app(settings)
    starter = _RecordingStarter()

    def fake_verify(_token: str, _request: object, audience: str | None = None) -> dict[str, object]:
        # Simulate ``verify_oauth2_token`` raising because the audience
        # Google validated the token for is different from the one we
        # require.
        raise ValueError(f"Audience mismatch: expected {audience!r}")

    monkeypatch.setattr(
        "google.oauth2.id_token.verify_oauth2_token",
        fake_verify,
    )
    with TestClient(app) as client:
        app.state.observer_starter = starter  # type: ignore[assignment]
        response = client.post(
            "/pubsub/agent-events",
            json=_envelope(_canonical_body()),
            headers={"authorization": "Bearer fake.token.value"},
        )
    assert response.status_code == 401
    assert response.json()["error"]["code"] == "pubsub_auth_invalid"
    assert starter.starts == []


def test_pubsub_route_in_production_rejects_untrusted_issuer(monkeypatch: pytest.MonkeyPatch) -> None:
    """A token signed by anything other than ``accounts.google.com`` is rejected."""

    settings = _production_settings()
    app = create_app(settings)
    starter = _RecordingStarter()

    def fake_verify(_token: str, _request: object, audience: str | None = None) -> dict[str, object]:
        # Simulate a successfully verified signature but with an issuer
        # we never accept. ``verify_oauth2_token`` normally rejects bad
        # issuers itself; the production helper does an explicit check
        # as a defence-in-depth backstop.
        return {"iss": "https://attacker.example.com", "aud": audience or ""}

    monkeypatch.setattr(
        "google.oauth2.id_token.verify_oauth2_token",
        fake_verify,
    )
    with TestClient(app) as client:
        app.state.observer_starter = starter  # type: ignore[assignment]
        response = client.post(
            "/pubsub/agent-events",
            json=_envelope(_canonical_body()),
            headers={"authorization": "Bearer fake.token.value"},
        )
    assert response.status_code == 401
    assert response.json()["error"]["code"] == "pubsub_auth_invalid_issuer"
    assert starter.starts == []


def test_pubsub_route_in_production_accepts_valid_token(monkeypatch: pytest.MonkeyPatch) -> None:
    """A token with the right issuer, audience, and identity proceeds to the
    observer (P0-2)."""

    settings = _production_settings()
    app = create_app(settings)
    starter = _RecordingStarter()

    def fake_verify(_token: str, _request: object, audience: str | None = None) -> dict[str, object]:
        return {
            "iss": "https://accounts.google.com",
            "aud": audience or "",
            "email": "service-537192856637@gcp-sa-pubsub.iam.gserviceaccount.com",
            "email_verified": True,
        }

    monkeypatch.setattr(
        "google.oauth2.id_token.verify_oauth2_token",
        fake_verify,
    )
    with TestClient(app) as client:
        app.state.observer_starter = starter  # type: ignore[assignment]
        response = client.post(
            "/pubsub/agent-events",
            json=_envelope(_canonical_body()),
            headers={"authorization": "Bearer fake.token.value"},
        )
    assert response.status_code == 200
    assert response.json()["outcome"] == "started"
    assert starter.starts and starter.starts[0].event.event_id == "evt-push-1"


def test_pubsub_route_in_non_production_skips_oidc_verification() -> None:
    """APP_ENV=test (or any non-production value) accepts requests without a token."""

    settings = _settings()  # app_env="test"
    app = create_app(settings)
    starter = _RecordingStarter()
    with TestClient(app) as client:
        app.state.observer_starter = starter  # type: ignore[assignment]
        # No Authorization header at all.
        response = client.post(
            "/pubsub/agent-events",
            json=_envelope(_canonical_body()),
        )
    assert response.status_code == 200
    assert response.json()["outcome"] == "started"


# ---------------------------------------------------------------------------
# OIDC service-account identity binding (P0-2)
# ---------------------------------------------------------------------------


_PUBSUB_PUSH_SA = "service-537192856637@gcp-sa-pubsub.iam.gserviceaccount.com"


def _verified_claims(
    audience: str | None = None,
    *,
    email: str = _PUBSUB_PUSH_SA,
    email_verified: bool = True,
) -> dict[str, object]:
    return {
        "iss": "https://accounts.google.com",
        "aud": audience or "https://retailtwin-api-511002.run.app",
        "email": email,
        "email_verified": email_verified,
    }


def test_pubsub_route_in_production_rejects_wrong_service_account(monkeypatch: pytest.MonkeyPatch) -> None:
    """A token for the right audience but a different Google-issued identity
    is rejected with 401 ``pubsub_auth_invalid_identity`` (P0-2)."""

    settings = _production_settings()
    app = create_app(settings)
    starter = _RecordingStarter()

    monkeypatch.setattr(
        "google.oauth2.id_token.verify_oauth2_token",
        lambda *_a, **_kw: _verified_claims(email="someone-else@example.com"),
    )
    with TestClient(app) as client:
        app.state.observer_starter = starter  # type: ignore[assignment]
        response = client.post(
            "/pubsub/agent-events",
            json=_envelope(_canonical_body()),
            headers={"authorization": "Bearer fake.token.value"},
        )
    assert response.status_code == 401
    assert response.json()["error"]["code"] == "pubsub_auth_invalid_identity"
    assert starter.starts == []


def test_pubsub_route_in_production_rejects_unverified_email(monkeypatch: pytest.MonkeyPatch) -> None:
    """A token whose ``email_verified`` claim is not ``True`` is rejected
    with 401 (P0-2)."""

    settings = _production_settings()
    app = create_app(settings)
    starter = _RecordingStarter()

    monkeypatch.setattr(
        "google.oauth2.id_token.verify_oauth2_token",
        lambda *_a, **_kw: _verified_claims(email_verified=False),
    )
    with TestClient(app) as client:
        app.state.observer_starter = starter  # type: ignore[assignment]
        response = client.post(
            "/pubsub/agent-events",
            json=_envelope(_canonical_body()),
            headers={"authorization": "Bearer fake.token.value"},
        )
    assert response.status_code == 401
    assert response.json()["error"]["code"] == "pubsub_auth_invalid_identity"
    assert starter.starts == []


def test_pubsub_route_in_production_rejects_missing_email_claim(monkeypatch: pytest.MonkeyPatch) -> None:
    """A token with no ``email`` claim is rejected with 401 (P0-2)."""

    settings = _production_settings()
    app = create_app(settings)
    starter = _RecordingStarter()

    monkeypatch.setattr(
        "google.oauth2.id_token.verify_oauth2_token",
        lambda *_a, **_kw: {
            "iss": "https://accounts.google.com",
            "aud": "https://retailtwin-api-511002.run.app",
            "email_verified": True,
        },
    )
    with TestClient(app) as client:
        app.state.observer_starter = starter  # type: ignore[assignment]
        response = client.post(
            "/pubsub/agent-events",
            json=_envelope(_canonical_body()),
            headers={"authorization": "Bearer fake.token.value"},
        )
    assert response.status_code == 401
    assert response.json()["error"]["code"] == "pubsub_auth_invalid_identity"
    assert starter.starts == []


def test_pubsub_route_in_production_with_empty_service_account_returns_503() -> None:
    """Production with an empty ``PUBSUB_PUSH_SERVICE_ACCOUNT`` fails
    closed with 503 ``pubsub_auth_misconfigured`` (P0-2)."""

    settings = _production_settings()
    # Override after construction so the empty string is honoured by the
    # pydantic field validator.
    object.__setattr__(settings, "pubsub_push_service_account", "")
    app = create_app(settings)
    starter = _RecordingStarter()
    with TestClient(app) as client:
        app.state.observer_starter = starter  # type: ignore[assignment]
        response = client.post(
            "/pubsub/agent-events",
            json=_envelope(_canonical_body()),
            headers={"authorization": "Bearer fake.token.value"},
        )
    assert response.status_code == 503
    assert response.json()["error"]["code"] == "pubsub_auth_misconfigured"
    assert starter.starts == []


def test_pubsub_route_in_production_with_unset_service_account_returns_503() -> None:
    """A production build that omits ``PUBSUB_PUSH_SERVICE_ACCOUNT``
    entirely (the default empty value) also fails closed with 503 (P0-2)."""

    settings = Settings(
        _env_file=None,
        app_env="production",
        store_id="store-001",
        store_fixture_path=DEFAULT_FIXTURE,
        app_base_url="https://retailtwin-api-511002.run.app",
    )
    app = create_app(settings)
    starter = _RecordingStarter()
    with TestClient(app) as client:
        app.state.observer_starter = starter  # type: ignore[assignment]
        response = client.post(
            "/pubsub/agent-events",
            json=_envelope(_canonical_body()),
            headers={"authorization": "Bearer fake.token.value"},
        )
    assert response.status_code == 503
    assert response.json()["error"]["code"] == "pubsub_auth_misconfigured"
    assert starter.starts == []


def test_pubsub_route_in_non_production_skips_identity_binding() -> None:
    """Dev / test bypasses the identity check entirely (P0-2 follow-up)."""

    settings = _settings()  # app_env="test"; pubsub_push_service_account=""
    app = create_app(settings)
    starter = _RecordingStarter()
    with TestClient(app) as client:
        app.state.observer_starter = starter  # type: ignore[assignment]
        # No Authorization header at all, no SA configured.
        response = client.post(
            "/pubsub/agent-events",
            json=_envelope(_canonical_body()),
        )
    assert response.status_code == 200
    assert response.json()["outcome"] == "started"