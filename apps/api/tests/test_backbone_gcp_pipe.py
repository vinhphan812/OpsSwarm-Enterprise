"""Tests for :class:`retailtwin_api.backbone_gcp.GcpPubSubEventPipe`.

The pipe wraps the synchronous ``google.cloud.pubsub_v1`` clients; we test
it with stub publisher and subscriber clients so no real GCP project is
touched.
"""

from __future__ import annotations

from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from retailtwin_api.backbone import BackboneError, PulledMessage
from retailtwin_api.backbone_gcp import GcpPubSubEventPipe
from retailtwin_api.schemas import StoreEvent


def _sale(event_id: str = "evt-1") -> StoreEvent:
    return StoreEvent(
        event_id=event_id,
        correlation_id="corr-1",
        event_type="sale.completed",
        store_id="store-001",
        sku="P017",
        quantity=1,
        occurred_at=datetime(2026, 10, 15, 12, 0, tzinfo=timezone.utc),
        source="synthetic-pos",
    )


class _Future:
    def __init__(self, message_id: str = "msg-1") -> None:
        self._message_id = message_id

    def result(self, timeout: float | None = None) -> str:
        return self._message_id


class _PublisherStub:
    """Stub for :class:`google.cloud.pubsub_v1.PublisherClient`."""

    def __init__(self) -> None:
        self.calls: list[dict[str, object]] = []
        self._future = _Future()

    def publish(self, topic: str, data: bytes, **kwargs: str) -> _Future:
        self.calls.append({"topic": topic, "data": data, **kwargs})
        return self._future


class _SubscriberStub:
    """Stub for :class:`google.cloud.pubsub_v1.SubscriberClient`."""

    def __init__(self) -> None:
        self.pull_calls: list[dict[str, object]] = []
        self.ack_calls: list[dict[str, object]] = []
        self._next_response: object | None = None

    def queue_response(self, response: object) -> None:
        self._next_response = response

    def pull(
        self,
        request: dict[str, object],
        timeout: float | None = None,
    ) -> object:
        self.pull_calls.append({"request": dict(request), "timeout": timeout})
        return self._next_response

    def acknowledge(
        self,
        request: dict[str, object],
        timeout: float | None = None,
    ) -> None:
        self.ack_calls.append({"request": dict(request), "timeout": timeout})

    def modify_ack_deadline(
        self,
        request: dict[str, object],
        timeout: float | None = None,
    ) -> None:
        self.ack_calls.append({"request": dict(request), "timeout": timeout})


def _build_pipe(
    subscriber: _SubscriberStub | None = None,
) -> tuple[GcpPubSubEventPipe, _PublisherStub, _SubscriberStub]:
    publisher = _PublisherStub()
    sub = subscriber or _SubscriberStub()
    pipe = GcpPubSubEventPipe(
        project="retailtwin-ai-511002",
        topic="store-events",
        subscription="store-events-agent",
        publisher=publisher,
        subscriber_factory=lambda: sub,
    )
    return pipe, publisher, sub


# ---------------------------------------------------------------------------
# Construction
# ---------------------------------------------------------------------------


def test_construct_requires_project() -> None:
    with pytest.raises(BackboneError, match="project"):
        GcpPubSubEventPipe(
            project="",
            topic="store-events",
            subscription="store-events-agent",
            publisher=MagicMock(),
            subscriber_factory=lambda: MagicMock(),
        )


def test_construct_requires_topic() -> None:
    with pytest.raises(BackboneError, match="topic"):
        GcpPubSubEventPipe(
            project="proj",
            topic="",
            subscription="store-events-agent",
            publisher=MagicMock(),
            subscriber_factory=lambda: MagicMock(),
        )


def test_construct_requires_subscription() -> None:
    with pytest.raises(BackboneError, match="subscription"):
        GcpPubSubEventPipe(
            project="proj",
            topic="store-events",
            subscription="",
            publisher=MagicMock(),
            subscriber_factory=lambda: MagicMock(),
        )


def test_topic_and_subscription_paths_are_absolute() -> None:
    pipe, _, _ = _build_pipe()
    assert pipe.topic_path == "projects/retailtwin-ai-511002/topics/store-events"
    assert pipe.subscription_path == "projects/retailtwin-ai-511002/subscriptions/store-events-agent"


# ---------------------------------------------------------------------------
# publish
# ---------------------------------------------------------------------------


def test_publish_uses_canonical_body_and_attributes() -> None:
    pipe, publisher, _ = _build_pipe()
    pipe.publish(_sale())
    assert len(publisher.calls) == 1
    call = publisher.calls[0]
    assert call["topic"] == pipe.topic_path
    assert isinstance(call["data"], bytes)
    assert b"sale.completed" in call["data"]
    assert call["event_id"] == "evt-1"
    assert call["correlation_id"] == "corr-1"
    assert call["store_id"] == "store-001"
    assert call["event_type"] == "sale.completed"


def test_publish_rejects_non_sale_event() -> None:
    pipe, publisher, _ = _build_pipe()
    bad = _sale().model_copy(update={"event_type": "inventory.adjusted"})
    with pytest.raises(BackboneError, match="sale.completed"):
        pipe.publish(bad)
    assert publisher.calls == []


def test_publish_caches_publisher_across_calls() -> None:
    """First publish must call the factory once; subsequent calls reuse it."""

    factory_calls: list[int] = []

    class _CountingPublisher:
        def __init__(self) -> None:
            factory_calls.append(len(factory_calls) + 1)

        def publish(self, topic: str, data: bytes, **kwargs: str) -> _Future:
            return _Future()

    pipe = GcpPubSubEventPipe(
        project="proj",
        topic="store-events",
        subscription="store-events-agent",
        publisher=None,
        subscriber_factory=lambda: _SubscriberStub(),
    )
    # Force the lazy factory path by patching the module's PublisherClient.
    import retailtwin_api.backbone_gcp as bgcp

    original = bgcp._default_subscriber_factory
    bgcp._default_subscriber_factory = lambda: _SubscriberStub()  # type: ignore[assignment]
    try:
        # Swap the PublisherClient import site.
        import google.cloud.pubsub_v1 as pubsub_v1

        original_client = pubsub_v1.PublisherClient
        pubsub_v1.PublisherClient = _CountingPublisher  # type: ignore[assignment]
        try:
            pipe.publish(_sale("evt-a"))
            pipe.publish(_sale("evt-b"))
        finally:
            pubsub_v1.PublisherClient = original_client  # type: ignore[assignment]
    finally:
        bgcp._default_subscriber_factory = original  # type: ignore[assignment]
    assert factory_calls == [1]


# ---------------------------------------------------------------------------
# pull
# ---------------------------------------------------------------------------


def _received(ack_id: str, data: bytes, attributes: dict[str, str]) -> SimpleNamespace:
    return SimpleNamespace(
        ack_id=ack_id,
        message=SimpleNamespace(
            data=data,
            attributes=attributes,
            publish_time=SimpleNamespace(rfc3339=lambda: "2026-10-15T12:00:00Z"),
        ),
    )


def test_pull_decodes_messages() -> None:
    subscriber = _SubscriberStub()
    body = b'{"event_id":"evt-1","correlation_id":"corr-1","event_type":"sale.completed","store_id":"store-001","sku":"P017","quantity":1,"occurred_at":"2026-10-15T12:00:00Z","source":"synthetic-pos"}'
    subscriber.queue_response(
        SimpleNamespace(
            received_messages=[
                _received("ack-1", body, {"event_id": "evt-1", "correlation_id": "corr-1"}),
            ]
        )
    )
    pipe, _, sub = _build_pipe(subscriber=subscriber)
    messages = pipe.pull(limit=5)
    assert len(messages) == 1
    assert messages[0].ack_id == "ack-1"
    assert messages[0].body == body.decode("utf-8")
    assert messages[0].attributes == {"event_id": "evt-1", "correlation_id": "corr-1"}
    assert messages[0].publish_time == "2026-10-15T12:00:00Z"
    assert sub.pull_calls == [{"request": {"subscription": pipe.subscription_path, "max_messages": 5}, "timeout": 10.0}]


def test_pull_clamps_limit_to_min_one() -> None:
    subscriber = _SubscriberStub()
    subscriber.queue_response(SimpleNamespace(received_messages=[]))
    pipe, _, _ = _build_pipe(subscriber=subscriber)
    pipe.pull(limit=0)
    assert subscriber.pull_calls[0]["request"]["max_messages"] == 1


def test_pull_clamps_limit_to_max_one_hundred() -> None:
    subscriber = _SubscriberStub()
    subscriber.queue_response(SimpleNamespace(received_messages=[]))
    pipe, _, _ = _build_pipe(subscriber=subscriber)
    pipe.pull(limit=999)
    assert subscriber.pull_calls[0]["request"]["max_messages"] == 100


def test_pull_skips_messages_without_a_payload() -> None:
    subscriber = _SubscriberStub()
    subscriber.queue_response(
        SimpleNamespace(
            received_messages=[
                SimpleNamespace(ack_id="ack-1", message=None),
                _received(
                    "ack-2",
                    b"{}",
                    {"event_id": "x"},
                ),
            ]
        )
    )
    pipe, _, _ = _build_pipe(subscriber=subscriber)
    messages = pipe.pull()
    assert [m.ack_id for m in messages] == ["ack-2"]


def test_pull_returns_empty_list_when_no_messages() -> None:
    subscriber = _SubscriberStub()
    subscriber.queue_response(SimpleNamespace(received_messages=[]))
    pipe, _, _ = _build_pipe(subscriber=subscriber)
    assert pipe.pull() == []


# ---------------------------------------------------------------------------
# ack
# ---------------------------------------------------------------------------


def test_ack_calls_subscriber_with_subscription_and_ack_id() -> None:
    pipe, _, subscriber = _build_pipe()
    pipe.ack("ack-1")
    assert subscriber.ack_calls == [
        {"request": {"subscription": pipe.subscription_path, "ack_ids": ["ack-1"]}, "timeout": 10.0}
    ]


def test_ack_rejects_empty_ack_id() -> None:
    pipe, _, subscriber = _build_pipe()
    with pytest.raises(BackboneError, match="empty ack id"):
        pipe.ack("")
    assert subscriber.ack_calls == []


def test_ack_rejects_ack_id_with_newline() -> None:
    pipe, _, subscriber = _build_pipe()
    with pytest.raises(BackboneError, match="empty ack id"):
        pipe.ack("ack\n1")
    assert subscriber.ack_calls == []


# ---------------------------------------------------------------------------
# Integration with the EventPipe Protocol
# ---------------------------------------------------------------------------


def test_satisfies_event_pipe_protocol() -> None:
    from retailtwin_api.backbone import EventPipe

    pipe, _, _ = _build_pipe()
    # EventPipe is a typing.Protocol without @runtime_checkable; assert the
    # structural shape rather than rely on isinstance().
    for method in EventPipe.__annotations__:
        assert hasattr(pipe, method)
        assert callable(getattr(pipe, method))


def test_pull_message_is_pulled_message_type() -> None:
    subscriber = _SubscriberStub()
    subscriber.queue_response(
        SimpleNamespace(
            received_messages=[_received("ack-1", b"{}", {"event_id": "evt-1"})]
        )
    )
    pipe, _, _ = _build_pipe(subscriber=subscriber)
    [message] = pipe.pull()
    assert isinstance(message, PulledMessage)