# 0023. Autonomous Pub/Sub event trigger for the FlagshipController

Date: 2026-10-15

## Status

Accepted

## Context

The flagship controller (issue #41, ADR section "Flagship Controller") exposes a deterministic autonomous chain over HTTP: ``POST /flagship/start`` runs the canonical event → investigate → plan → simulate → guard → commit → verify loop on a reset Live Twin. Until now, the only way to drive that loop was a direct HTTP call from an operator or a dashboard button. The FE in ``apps/web`` had no path to see the chain run end-to-end without a human action, and demo recordings stalled waiting on someone to press a button.

Three constraints already accepted:

- ADR 0010 — start one investigation per sale.completed, no prompt.
- ``EventPipe`` protocol in ``apps/api/retailtwin_api/backbone.py`` — the canonical publish/pull/ack surface for store events.
- The flagship controller's public command surface is ``start(FlagshipRequest)``, ``reset()``, ``status()``, ``is_configured`` (no signature change allowed).

The codebase already had a Pub/Sub topic ``store-events`` and an analytics subscription ``store-events-analytics``. The agent needs a second subscription on the same topic so Pub/Sub pushes messages to the Cloud Run service via HTTP; the analytics path stays untouched. The agent subscription ``store-events-agent`` exists in the project but had no consumer.

We also need a continuous feed so the FE sees new data without a human pressing a button. A scheduled publisher that emits one canonical ``sale.completed`` every 45 seconds keeps the EventLog fresh; the EventLog already dedupes by ``event_id``, so each tick lands as a new event.

## Decision

Wire the autonomous trigger inside the FastAPI lifespan:

1. ``apps/api/retailtwin_api/backbone_gcp.py`` adds ``GcpPubSubEventPipe`` — an ``EventPipe`` implementation backed by the synchronous ``google.cloud.pubsub_v1`` clients. The pipe publishes to ``projects/{project}/topics/store-events`` and pulls/acks on ``projects/{project}/subscriptions/store-events-agent``. The publisher is built once and cached. The subscriber is built per pull call: the HTTP push handler is short-lived and a per-call client keeps the ack-deadline window tight without background threads.
2. ``apps/api/retailtwin_api/flagship/agent_starter.py`` adds ``FlagshipInvestigationStarter`` — the synchronous→async bridge. ``observe_message`` is sync; ``FlagshipController.start`` is async. The starter looks up the controller via a callable, raises ``ObservationError`` when the controller is missing or not configured (so Pub/Sub re-delivers), then drives ``start()`` in a fresh ``asyncio.run`` loop because the consumer runs outside the FastAPI event loop (via ``asyncio.to_thread`` in the lifespan task). The production autonomous path uses ``FlagshipInvestigationStarter.start_investigation_for_event(start.event)`` — it does **not** call ``controller.reset()`` and it does **not** inject the deterministic ``stale_block_enabled=True`` flag. The incoming ``StoreEvent`` is preserved end-to-end (``event_id``, ``sku``, ``quantity``, ``occurred_at``, ``store_id``, ``correlation_id``) so a real sale investigates the current Live Twin state, not a freshly seeded demo baseline.
3. ``apps/api/retailtwin_api/demand_surge.py`` adds ``DemandSurgeScheduler`` — an ``asyncio.create_task`` loop that publishes one canonical ``sale.completed`` every ``AUTONOMOUS_TRIGGER_INTERVAL_SECONDS`` (default 45). Each tick uses a fresh ``event_id`` (``secrets.token_hex(8)``); the existing ``EventLog`` dedupes by ``event_id``, so every tick lands as a new event.
4. ``apps/api/retailtwin_api/main.py`` ``create_app`` installs a ``lifespan`` context manager. It builds the ``EventPipe`` (always ``MemoryPipe``), the ``MemoryActivationLedger``, the ``MemoryQuarantine``, and the ``FlagshipInvestigationStarter``. When ``AUTONOMOUS_TRIGGER_ENABLED=true`` **and** the process is not in production (or ``AUTONOMOUS_PUBSUB_PULL_DISABLED_IN_PRODUCTION=false``), it spawns an ``asyncio.Task`` running ``consume_available`` in a ``while True / asyncio.sleep``; when ``AUTONOMOUS_SCHEDULED_PUBLISHER_ENABLED=true`` it starts the ``DemandSurgeScheduler``. Both are torn down on lifespan exit (cancel + await). In production the subscription ``store-events-agent`` is **push-only** and points at ``POST /pubsub/agent-events``; the lifespan does NOT start a background pull loop in production because push and pull are mutually exclusive on one Pub/Sub subscription. Dev/test use ``MemoryPipe`` + ``_autonomous_trigger_loop`` for offline exercise.
5. ``apps/api/retailtwin_api/routes.py`` adds ``POST /pubsub/agent-events`` — the HTTP push endpoint Cloud Run exposes for the Pub/Sub subscription. It decodes the envelope, builds a ``PulledMessage``, and feeds it through the same ``observe_message`` path the in-process consumer uses. A successful ``observe_message`` returns 200; a rejected payload still returns 200 after the quarantine records it (Pub/Sub does not retry on 2xx); an ``ObservationError`` returns 500 so Pub/Sub re-delivers.
6. ``apps/api/retailtwin_api/routes.py`` ``accept_event`` publishes the accepted event to ``app.state.event_pipe`` after the ``EventLog.accept`` path. This makes external ``POST /events`` calls also drive the agent.
7. ``apps/api/retailtwin_api/settings.py`` adds the fields, all off by default in dev: ``autonomous_trigger_enabled``, ``autonomous_scheduled_publisher_enabled``, ``autonomous_trigger_interval_seconds`` (45, 5..3600), ``autonomous_pubsub_project``, ``autonomous_pubsub_subscription`` (``store-events-agent``), ``autonomous_pubsub_pull_disabled_in_production`` (True — production is push-only), ``pubsub_push_service_account`` (the canonical ``service-<PROJECT_NUMBER>@gcp-sa-pubsub.iam.gserviceaccount.com`` SA that Pub/Sub's push authenticator issues tokens for).
8. ``.env.example`` documents the new vars. The trigger is OFF by default in dev so a ``MemoryPipe`` never auto-publishes.

OIDC bearer-token verification lives in ``_verify_pubsub_push_bearer`` (production only). The helper requires an ``Authorization: Bearer <token>`` header, verifies the JWT signature via ``google.oauth2.id_token.verify_oauth2_token``, checks ``iss = https://accounts.google.com``, checks ``aud = APP_BASE_URL``, and (in production) checks that ``email_verified`` is ``True`` **and** ``email == settings.pubsub_push_service_account``. Production returns ``401 pubsub_auth_invalid_identity`` on a SA mismatch and ``401 pubsub_auth_invalid_identity`` when ``email_verified`` is not ``True``. Production returns ``503 pubsub_auth_misconfigured`` when ``PUBSUB_PUSH_SERVICE_ACCOUNT`` is empty (fail closed). Non-production environments skip the helper entirely so the test suite and local development can drive ``POST /pubsub/agent-events`` without a real token.

The canonical store id and SKU come from the demand-surge constants (``. ``P018'').

The ``google-cloud-pubsub`` dependency is added to ``pyproject.toml``. No API key is read or stored; production uses Application Default Credentials on the existing ``retailtwin-agent@retailtwin-ai-511002.iam.gserviceaccount.com`` SA, which already has ``roles/pubsub.subscriber``.

## Consequences

- The FE in ``apps/web`` sees a continuous feed of ``sale.completed`` events when ``AUTONOMOUS_SCHEDULED_PUBLISHER_ENABLED=true``; each tick triggers a flagship run when the FlagshipInvestigationStarter and controller are configured.
- ``POST /events`` keeps the original 200/201 semantics for the EventLog but additionally hands the event to the pipe. A duplicate ``event_id`` does NOT re-publish (the EventLog dedupe path returns early); the agent chain dedupes on the same key (Activation Ledger), so the second delivery is a no-op.
- Production deploy does NOT need ``AUTONOMOUS_TRIGGER_ENABLED=true``. Real events arrive via the OIDC-verified push endpoint; the scheduled publisher's publishes go to ``MemoryPipe`` in production (production real events come from real checkouts, not from the demo scheduler).
- ``_verify_pubsub_push_bearer`` now binds the OIDC token to the expected Pub/Sub push service-account identity. A different Google-issued ID token for the same ``APP_BASE_URL`` audience cannot invoke the autonomous agent endpoint; an unset ``PUBSUB_PUSH_SERVICE_ACCOUNT`` in production fails closed with 503.
- Production ``GcpPubSubEventPipe`` is no longer instantiated in the lifespan. The class is kept as a library for non-production tests and any future pull-mode consumers.
- The agent subscription ``store-events-agent`` adds a second consumer to the existing ``store-events`` topic; analytics delivery to BigQuery via ``store-events-analytics`` is unchanged.
- ``EventLog`` dedupe already protects against duplicate ``event_id``s, so the scheduler's per-tick fresh id is the contract that drives new events.

## Alternatives considered

- **Background worker Cloud Run service.** A separate consumer service that pulls from Pub/Sub via streaming-pull would own the ack-deadline management and the agent dispatch. We rejected this because it doubles the deploy surface, doubles the IAM scope, and adds a second Cold Start path. The HTTP push path uses the same Cloud Run instance the FE already hits, so operational cost stays on one service.
- **Cloud Functions.** Pub/Sub push can target a Cloud Function without a server. We rejected this because the consumer needs the FlagshipController, the Live Twin repository, and the canonical services — all of which live in the FastAPI service. Splitting them out forces a network hop for every flagship run.
- **Skip the scheduled publisher.** Rely on the operator pressing ``POST /flagship/start`` to drive the FE. We rejected this because the demo and the FE smoke test both need continuous data without a human in the loop.

- Pull request:
- Issue:
- Supersedes:
- Superseded by: