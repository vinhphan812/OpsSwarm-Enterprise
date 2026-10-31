"""Concurrent lease-takeover and revision-CAS fault injection (ADR-031, Issue #70).

ADR-031 "Test 2: Concurrent Leader Race and CAS Enforcement" requires that two
parallel processes attempting to claim the same run lease -- or to update run
state concurrently -- are serialised by ``SELECT FOR UPDATE`` and by the
revision CAS, so that the loser observes zero rows mutated.

Phase 2 owns the *schema* half of that contract.  This module proves the
schema can actually carry it, by running ADR-031's own SQL against a real
PostgreSQL server with genuine concurrent sessions:

* two standbys race to take over the same expired lease under the ADR's
  documented authorisation binding -- exactly one must win, and the loser's
  authorisation must remain unconsumed;
* two writers race to update the same run under the ADR's revision CAS --
  exactly one must win, and the loser's write must mutate zero rows.

These are live-database fault-injection tests, so they skip cleanly when
``HA_TEST_DATABASE_URL`` is not configured.  The CI workflow provisions a
PostgreSQL service container so this module actually runs there rather than
silently skipping.
"""

from __future__ import annotations

import os
import threading
from typing import Iterator

import pytest

alembic_command_module = pytest.importorskip(
    "alembic.command", reason="alembic is required for the HA lease concurrency test"
)
alembic_config_module = pytest.importorskip(
    "alembic.config", reason="alembic is required for the HA lease concurrency test"
)
sa = pytest.importorskip(
    "sqlalchemy", reason="SQLAlchemy is required for the HA lease concurrency test"
)

try:  # pragma: no cover - exercised only when a driver is installed
    import psycopg2  # noqa: F401
except ImportError:  # pragma: no cover - exercised only when a driver is missing
    psycopg2 = None  # type: ignore[assignment]


pytestmark = [pytest.mark.fault, pytest.mark.integration]


REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
ALEMBIC_INI = os.path.join(REPO_ROOT, "alembic.ini")


def _database_url() -> str | None:
    url = os.environ.get("HA_TEST_DATABASE_URL") or os.environ.get("HA_DATABASE_URL")
    if not url:
        return None
    if url.startswith("postgresql://"):
        return url.replace("postgresql://", "postgresql+psycopg2://", 1)
    return url


def _assert_disposable_database(url: str) -> None:
    """Refuse to reset a schema in a database that is not clearly a test one."""
    name = url.rsplit("/", 1)[-1].split("?", 1)[0]
    if "test" not in name.lower():
        pytest.fail(
            "HA_TEST_DATABASE_URL must point at a disposable test database "
            f"(database name {name!r} does not contain 'test'); refusing to reset its schema"
        )


@pytest.fixture(scope="module")
def database_url() -> str:
    url = _database_url()
    if not url:
        pytest.skip(
            "HA_TEST_DATABASE_URL is not set; skipping the live PostgreSQL lease concurrency test"
        )
    if psycopg2 is None:
        pytest.skip(
            "psycopg2 is not installed; skipping the live PostgreSQL lease concurrency test"
        )
    _assert_disposable_database(url)
    return url


@pytest.fixture(scope="module")
def engine(database_url: str) -> Iterator[object]:
    eng = sa.create_engine(database_url, future=True)
    try:
        with eng.connect() as conn:
            conn.execute(sa.text("SELECT 1"))
    except Exception as exc:  # pragma: no cover - environment dependent
        pytest.skip(f"PostgreSQL is not reachable at the configured URL: {exc}")
    yield eng
    eng.dispose()


@pytest.fixture(scope="module")
def monkeypatch_module():
    """Module-scoped environment patching (``monkeypatch`` is function-scoped)."""
    patcher = pytest.MonkeyPatch()
    try:
        yield patcher
    finally:
        patcher.undo()


@pytest.fixture(scope="module")
def alembic_config(database_url: str, monkeypatch_module):
    monkeypatch_module.setenv("HA_DATABASE_URL", database_url)
    cfg = alembic_config_module.Config(ALEMBIC_INI)
    cfg.set_main_option("script_location", os.path.join(REPO_ROOT, "migrations"))
    cfg.set_main_option("sqlalchemy.url", database_url.replace("%", "%%"))
    return cfg


@pytest.fixture
def migrated_db(alembic_config, engine) -> Iterator[None]:
    """Yield with the HA schema applied, then tear it back down."""
    with engine.begin() as conn:
        conn.execute(sa.text("DROP SCHEMA IF EXISTS public CASCADE"))
        conn.execute(sa.text("CREATE SCHEMA public"))

    alembic_command_module.upgrade(alembic_config, "head")
    try:
        yield
    finally:
        alembic_command_module.downgrade(alembic_config, "-1")


# --------------------------------------------------------------------------- #
# ADR-031 SQL, transcribed from the ADR's lease lifecycle section
# --------------------------------------------------------------------------- #

#: ADR-031 "Takeover of an expired lease, permitted only with a matching
#: operator authorisation".  The ``observed_epoch`` binding ties the
#: authorisation to one lease generation, and ``consumed_epoch IS NULL`` stops
#: the same authorisation being spent twice.
TAKEOVER_SQL = """
UPDATE run_leases l
SET    owner_id   = :me,
       epoch      = l.epoch + 1,
       expires_at = NOW() + INTERVAL '30 seconds'
FROM lease_takeover_authorisations a
WHERE l.run_id         = :run_id
  AND a.run_id         = l.run_id
  AND a.observed_epoch = l.epoch
  AND a.consumed_epoch IS NULL
  AND l.expires_at     <= NOW()
RETURNING l.owner_id, l.epoch, l.expires_at
"""

#: ADR-031 "Optimistic CAS: UPDATE only if revision matches".
#: ``rowcount == 0`` is the signal that the loser must treat as
#: ``StaleDataError``.
REVISION_CAS_SQL = """
UPDATE runs
SET    run_data = :run_data,
       revision = revision + 1,
       updated_at = NOW()
WHERE  run_id = :run_id
  AND  revision = :expected_revision
"""


def _seed_expired_lease(engine, run_id: str, epoch: int = 1) -> None:
    """Create a run whose lease has expired and is therefore takeover-eligible."""
    with engine.begin() as conn:
        conn.execute(
            sa.text(
                "INSERT INTO runs (run_id, issue_number, state, run_data) "
                "VALUES (:run_id, 42, 'running', '{}'::jsonb)"
            ),
            {"run_id": run_id},
        )
        conn.execute(
            sa.text(
                "INSERT INTO run_leases (run_id, owner_id, epoch, expires_at) "
                "VALUES (:run_id, 'owner-a', :epoch, NOW() - INTERVAL '1 hour')"
            ),
            {"run_id": run_id, "epoch": epoch},
        )


def _authorise_takeover(engine, run_id: str, observed_epoch: int) -> None:
    """Record an operator authorisation bound to ``observed_epoch``."""
    with engine.begin() as conn:
        conn.execute(
            sa.text(
                "INSERT INTO lease_takeover_authorisations "
                "(run_id, observed_epoch, approved_by, reason) "
                "VALUES (:run_id, :observed_epoch, 'operator-1', 'primary paused')"
            ),
            {"run_id": run_id, "observed_epoch": observed_epoch},
        )


def _try_takeover(engine, run_id: str, me: str) -> tuple[bool, int | None]:
    """Attempt the ADR takeover and report ``(acquired, epoch)``.

    The whole attempt runs inside one transaction that first takes the
    ``SELECT ... FOR UPDATE`` row lock, exactly as ADR-031's ``ACQUIRE_LEASE``
    pseudocode does.  A standby that loses the race must see ``rowcount == 0``
    and commit nothing.
    """
    with engine.begin() as conn:
        locked = conn.execute(
            sa.text(
                "SELECT owner_id, epoch, expires_at FROM run_leases "
                "WHERE run_id = :run_id FOR UPDATE"
            ),
            {"run_id": run_id},
        ).one()

        # The lease must still look expired to this process; otherwise the
        # takeover is not eligible and the process is a plain loser.
        row = conn.execute(
            sa.text(TAKEOVER_SQL),
            {"run_id": run_id, "me": me},
        ).first()

        if row is None:
            return False, None

        # Consume the authorisation in the same transaction, so the grant and
        # the spend are atomic.
        conn.execute(
            sa.text(
                "UPDATE lease_takeover_authorisations SET consumed_epoch = :granted "
                "WHERE run_id = :run_id AND observed_epoch = :observed "
                "AND consumed_epoch IS NULL"
            ),
            {"granted": row.epoch, "run_id": run_id, "observed": locked.epoch},
        )
        return True, row.epoch


def test_concurrent_takeover_grants_the_lease_to_exactly_one_standby(engine, migrated_db) -> None:
    """Two standbys racing for one expired lease: exactly one may win.

    This is the ADR-031 concurrent-leader race at the schema level.  Both
    standbys hold a matching operator authorisation for the same observed
    epoch, so nothing but the row lock and the epoch binding may stop the
    second one.  The loser must mutate zero rows: it must not take the lease,
    must not increment the epoch, and must leave the authorisation unspent.
    """
    run_id = "run-race-takeover"
    _seed_expired_lease(engine, run_id, epoch=3)
    _authorise_takeover(engine, run_id, observed_epoch=3)

    results: dict[str, tuple[bool, int | None]] = {}
    barrier = threading.Barrier(2, timeout=30)
    errors: list[BaseException] = []

    def contend(me: str) -> None:
        try:
            # Both standbys reach the row lock at the same moment, so the race
            # is genuine rather than merely sequential.
            barrier.wait()
            results[me] = _try_takeover(engine, run_id, me)
        except BaseException as exc:  # noqa: BLE001 - re-raised on the main thread
            errors.append(exc)

    threads = [threading.Thread(target=contend, args=(me,)) for me in ("standby-b", "standby-c")]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=60)

    assert not errors, f"standby attempt raised: {errors!r}"
    assert len(results) == 2, f"both standbys must have completed, got {results!r}"

    winners = [me for me, (acquired, _) in results.items() if acquired]
    losers = [me for me, (acquired, _) in results.items() if not acquired]
    assert len(winners) == 1, f"exactly one standby may win the takeover, got {results!r}"
    assert len(losers) == 1, f"exactly one standby must lose, got {results!r}"

    winner = winners[0]
    loser = losers[0]
    assert results[winner][1] == 4, "the winner must receive the incremented epoch"
    assert results[loser][1] is None, "the loser must not receive an epoch"

    with engine.begin() as conn:
        lease = conn.execute(
            sa.text("SELECT owner_id, epoch FROM run_leases WHERE run_id = :run_id"),
            {"run_id": run_id},
        ).one()
        assert lease.owner_id == winner, "the lease must belong to the winner"
        assert lease.epoch == 4, "the epoch must be incremented exactly once"

        # The loser must have mutated zero rows: the authorisation is spent
        # exactly once, by the winner's generation.
        auth = conn.execute(
            sa.text(
                "SELECT consumed_epoch FROM lease_takeover_authorisations "
                "WHERE run_id = :run_id AND observed_epoch = 3"
            ),
            {"run_id": run_id},
        ).one()
        assert auth.consumed_epoch == 4, "the authorisation must be consumed exactly once"


def test_concurrent_revision_cas_mutates_zero_rows_for_the_loser(engine, migrated_db) -> None:
    """Two writers racing to update one run: exactly one may win.

    ADR-031's revision CAS is the second half of "Test 2: Concurrent Leader
    Race and CAS Enforcement".  The loser must observe ``rowcount == 0`` and
    commit nothing, which is what the caller turns into ``StaleDataError``.
    """
    run_id = "run-race-cas"
    with engine.begin() as conn:
        conn.execute(
            sa.text(
                "INSERT INTO runs (run_id, issue_number, state, run_data) "
                "VALUES (:run_id, 42, 'running', '{\"winner\": 0}'::jsonb)"
            ),
            {"run_id": run_id},
        )

    rowcounts: dict[str, int] = {}
    barrier = threading.Barrier(2, timeout=30)
    errors: list[BaseException] = []

    def contend(me: str) -> None:
        try:
            barrier.wait()
            with engine.begin() as conn:
                result = conn.execute(
                    sa.text(REVISION_CAS_SQL),
                    {
                        "run_id": run_id,
                        "run_data": '{"winner": "%s"}' % me,
                        "expected_revision": 1,
                    },
                )
                rowcounts[me] = result.rowcount
        except BaseException as exc:  # noqa: BLE001 - re-raised on the main thread
            errors.append(exc)

    threads = [threading.Thread(target=contend, args=(me,)) for me in ("writer-b", "writer-c")]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=60)

    assert not errors, f"writer attempt raised: {errors!r}"
    assert len(rowcounts) == 2, f"both writers must have completed, got {rowcounts!r}"

    assert sorted(rowcounts.values()) == [0, 1], (
        "exactly one writer may update the row; the loser must observe "
        f"rowcount == 0, got {rowcounts!r}"
    )

    with engine.begin() as conn:
        run = conn.execute(
            sa.text("SELECT revision, run_data FROM runs WHERE run_id = :run_id"),
            {"run_id": run_id},
        ).one()
        assert run.revision == 2, "the revision must be incremented exactly once"
        winner = next(me for me, count in rowcounts.items() if count == 1)
        assert run.run_data["winner"] == winner, "the stored payload must be the winner's"


def test_stale_epoch_holder_cannot_renew_a_taken_over_lease(engine, migrated_db) -> None:
    """A fenced holder's renewal must affect zero rows.

    ADR-031's renewal statement is refused unless the caller's epoch still
    matches and the lease has not expired, so a process that was taken over
    cannot extend the new owner's lease or win it back.
    """
    run_id = "run-fenced-renewal"
    _seed_expired_lease(engine, run_id, epoch=1)
    _authorise_takeover(engine, run_id, observed_epoch=1)

    acquired, epoch = _try_takeover(engine, run_id, "standby-b")
    assert acquired is True
    assert epoch == 2

    with engine.begin() as conn:
        result = conn.execute(
            sa.text(
                "UPDATE run_leases SET expires_at = NOW() + INTERVAL '30 seconds' "
                "WHERE run_id = :run_id AND owner_id = :me AND epoch = :epoch "
                "AND expires_at > NOW()"
            ),
            {"run_id": run_id, "me": "owner-a", "epoch": 1},
        )
        assert result.rowcount == 0, "the fenced previous owner must not be able to renew the lease"

        lease = conn.execute(
            sa.text("SELECT owner_id, epoch FROM run_leases WHERE run_id = :run_id"),
            {"run_id": run_id},
        ).one()
        assert lease.owner_id == "standby-b"
        assert lease.epoch == 2
