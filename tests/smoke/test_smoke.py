"""Canonical smoke checks executed by the CI layer matrix."""

from opsswarm.models import RunState


def test_package_imports_and_state_contract():
    """The installed package exposes the lifecycle states used by CI."""
    assert RunState.OPEN.value == "OPEN"
