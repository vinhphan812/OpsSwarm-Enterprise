from opsswarm.models import Risk
from opsswarm.policy import PolicyEngine


def test_classify_operation_branches():
    eng = PolicyEngine({})

    # Trigger 15
    assert eng.classify_operation(None) == Risk.RISKY_WRITE

    # Trigger 23
    assert eng.classify_operation("patch /admin/something") == Risk.DESTRUCTIVE
    assert eng.classify_operation("patch /some/path") == Risk.SAFE_WRITE

    # Trigger 27
    assert eng.classify_operation("unknown command") == Risk.RISKY_WRITE
