"""What the Decision Context Guard lets an autonomous decision do.

The policy is configuration, not model output. Defaults are conservative and
each limit can be set from the environment.
"""

from __future__ import annotations

import os
from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import timedelta

MOVE_PRODUCT = "move_product"
CHANGE_FACINGS = "change_facings"
REPLENISH_SHELF = "replenish_shelf"
ACTION_TYPES: frozenset[str] = frozenset({MOVE_PRODUCT, CHANGE_FACINGS, REPLENISH_SHELF})

FRESHNESS_ENV = "RETAILTWIN_DCG_FRESHNESS_SECONDS"
MAX_FACINGS_ENV = "RETAILTWIN_DCG_MAX_FACINGS"
MAX_ACTIONS_ENV = "RETAILTWIN_DCG_MAX_ACTIONS"
MAX_REPLENISH_ENV = "RETAILTWIN_DCG_MAX_REPLENISH_UNITS"


class PolicyConfigError(ValueError):
    """A policy variable is set but is not a positive integer."""


@dataclass(frozen=True)
class GuardPolicy:
    """Limits the guard enforces.

    ``max_facings`` stands in for slot capacity: the Live Twin does not store
    one. Past ``max_actions`` or ``max_replenish_units`` a person decides.
    """

    freshness: timedelta = timedelta(seconds=120)
    max_facings: int = 12
    max_actions: int = 5
    max_replenish_units: int = 200
    clock_skew: timedelta = timedelta(seconds=5)
    allowed_actions: frozenset[str] = field(default=ACTION_TYPES)

    @classmethod
    def from_env(cls, environ: Mapping[str, str] | None = None) -> GuardPolicy:
        env = os.environ if environ is None else environ
        default = cls()
        return cls(
            freshness=timedelta(
                seconds=_positive(env, FRESHNESS_ENV, int(default.freshness.total_seconds()))
            ),
            max_facings=_positive(env, MAX_FACINGS_ENV, default.max_facings),
            max_actions=_positive(env, MAX_ACTIONS_ENV, default.max_actions),
            max_replenish_units=_positive(env, MAX_REPLENISH_ENV, default.max_replenish_units),
        )


def _positive(env: Mapping[str, str], name: str, default: int) -> int:
    raw = env.get(name)
    if raw is None or not raw.strip():
        return default
    try:
        value = int(raw)
    except ValueError:
        raise PolicyConfigError(f"{name} must be a positive integer.") from None
    if value < 1:
        raise PolicyConfigError(f"{name} must be a positive integer.")
    return value
