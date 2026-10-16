"""Test-only stale-race injection for the flagship demo controller.

The flagship demo controller deliberately provokes a stale
``REFRESH_REQUIRED`` from the Decision Context Guard by advancing a single
SKU's Live Twin version between the planner and the guard's ``authorize``
call. That is a *non-decision* admin operation: there is no agent decision,
no authorization token, and no executor — only a Live Twin write that
exists to make the deterministic stale-race reproducible.

ADR 0016 reserves the only production mutation path for the guarded
Executor. A free function that calls
:meth:`LiveTwinRepository.commit_inventory` directly would violate that
contract, so this helper lives in its own module and refuses to run when
``APP_ENV`` is ``production``. The helper still calls ``commit_inventory``
itself — it has to, to bump a version — but the call site is restricted to
non-production environments and to the explicit test-helper opt-in.

Production invariants (enforced by
``tests/e2e/test_simulation_live_isolation.py``):

* the only module that may contain a free ``commit_inventory`` call site is
  :mod:`retailtwin_api.flagship._stale_bump`;
* every other production module must route writes through the guarded
  Executor (:mod:`retailtwin_api.agents.executor.executor`) or the seed
  boundary (:mod:`retailtwin_api.store`).

When the helper is called from a non-production environment the bump is
real: it advances the SKU version by one and decrements its shelf quantity
by one (clamped at zero). When called from ``APP_ENV=production`` it raises
immediately so a misconfiguration cannot silently bypass ADR 0016.
"""
from __future__ import annotations

import os

from retailtwin_api.firestore_twin import (
    LiveTwinRepository,
    TwinConflict,
)


# Values of ``APP_ENV`` that block the stale-race injection. ``production``
# is the only value that blocks it today; any other valid value (including
# ``development``, ``staging``, ``test``, ``e2e-smoke``) allows the helper
# to run. Normalisation matches :mod:`retailtwin_api.settings` so a stray
# casing cannot smuggle a production call through.
_PRODUCTION_ENVS = frozenset({"production"})


def _is_test_environment() -> bool:
    """True when the running process may inject stale races for the demo.

    The check reads the process-level ``APP_ENV`` (already validated by
    :mod:`retailtwin_api.settings`). Any non-production environment is
    allowed; production raises immediately so the helper cannot bypass the
    guarded Executor in Cloud Run.
    """
    app_env = os.environ.get("APP_ENV", "development").strip().lower()
    return app_env not in _PRODUCTION_ENVS


def bump_inventory_for_stale_block(
    twin: LiveTwinRepository, store_id: str, sku: str
) -> bool:
    """Advance a single SKU's Live Twin version without an agent decision.

    TEST-ONLY: this helper raises ``RuntimeError`` whenever ``APP_ENV`` is
    ``production``. The guarded Executor (ADR 0016) remains the only
    production mutation path; the helper exists only to make the flagship
    demo's deliberate ``REFRESH_REQUIRED`` race reproducible in
    development / staging / test / e2e-smoke environments.

    The bump reduces the SKU's shelf quantity by one (clamped at zero) and
    advances its version by one; the store-level ``v<N>`` advances with the
    SKU because :meth:`LiveTwinRepository.commit_inventory` always bumps the
    store version on a write.

    Returns:
        ``True`` when the bump landed, ``False`` when the SKU is missing or
        a concurrent change raised :class:`TwinConflict` because the
        optimistic-lock version moved underneath us.

    Raises:
        RuntimeError: when ``APP_ENV`` is ``production``. Production code
            must never bypass the guarded Executor.
    """
    if not _is_test_environment():
        raise RuntimeError(
            "bump_inventory_for_stale_block is test-only — production code "
            "must go through the guarded Executor (ADR 0016). Run the "
            "flagship demo in APP_ENV=development / staging / test / "
            "e2e-smoke."
        )
    current = twin.get_inventory(store_id, sku)
    if current is None:
        return False
    bumped = current.model_copy(
        update={
            "shelf_quantity": max(0, current.shelf_quantity - 1),
            "version": current.version + 1,
        }
    )
    try:
        twin.commit_inventory(store_id, [(bumped, current.version)])
    except TwinConflict:
        return False
    return True