"""Opt-in live proof that Gemini on Vertex calls get_inventory.

CI does not set RETAILTWIN_VERTEX_LIVE. The test reads Firestore and calls
generateContent. It does not write the Live Twin and it does not pass a gate.

Local setup, from a developer who already has Application Default Credentials
for project retailtwin-ai-511002:

    gcloud auth application-default login
    gcloud auth application-default set-quota-project retailtwin-ai-511002

Then, from apps/api:

    RETAILTWIN_VERTEX_LIVE=1 .venv/bin/python -m pytest tests/test_vertex_inventory_live.py -q

The model is gemini-2.5-flash in us-central1. Do not put an API key in the
environment. Do not set the flag in CI.
"""

from __future__ import annotations

import asyncio
import os

import pytest

from retailtwin_api.agents.orchestrator.inventory_read import read_inventory
from retailtwin_api.firestore_twin import FirestoreLiveTwinRepository
from retailtwin_api.llm.factory import LlmConfig, create_provider

pytestmark = pytest.mark.skipif(
    os.environ.get("RETAILTWIN_VERTEX_LIVE") != "1",
    reason="set RETAILTWIN_VERTEX_LIVE=1 to run one billed Gemini inventory read",
)

_PROJECT = "retailtwin-ai-511002"
_LOCATION = "us-central1"
_MODEL = "gemini-2.5-flash"
_STORE = "store-001"
_SKU = "P001"
_MISSING = "SKU-NOT-IN-STORE"


def test_live_gemini_get_inventory_matches_firestore() -> None:
    twin = FirestoreLiveTwinRepository()
    document = twin.get_inventory(_STORE, _SKU)
    assert document is not None
    assert twin.get_inventory(_STORE, _MISSING) is None
    before = document.model_dump()
    provider = create_provider(
        LlmConfig(
            provider="vertex_gemini",
            model=_MODEL,
            project_id=_PROJECT,
            location=_LOCATION,
            timeout=90,
        )
    )

    found = asyncio.run(
        read_inventory(
            twin,
            provider=provider,
            store_id=_STORE,
            sku=_SKU,
            correlation_id="issue-2-live-p001",
            model=_MODEL,
        )
    )
    missing = asyncio.run(
        read_inventory(
            twin,
            provider=provider,
            store_id=_STORE,
            sku=_MISSING,
            correlation_id="issue-2-live-missing",
            model=_MODEL,
        )
    )

    assert found.ok is True
    assert found.output == document.to_product_inventory()
    assert "updated_at" not in (found.output or {})
    assert missing.ok is False
    assert missing.error_code == "not_found"
    assert missing.output is None
    again = twin.get_inventory(_STORE, _SKU)
    assert again is not None
    assert again.model_dump() == before
    assert twin.get_inventory(_STORE, _MISSING) is None
