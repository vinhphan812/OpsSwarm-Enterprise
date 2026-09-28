# -*- coding: utf-8 -*-
"""Unit tests for Issue #26 — Task graph validation.

Tests validate_task_graph() and its four exception types:
  1. DuplicateTaskIdError      — duplicate task IDs rejected
  2. DanglingDependencyError   — non-existent depends_on target rejected
  3. CycleError               — cyclic dependency rejected
  4. DepthExceededError       — dependency depth > max_depth rejected

Normal DAGs (valid inputs) are also tested to ensure no false positives.
"""

import pytest

from opsswarm.validators import (
    CycleError,
    DepthExceededError,
    DuplicateTaskIdError,
    DanglingDependencyError,
    validate_task_graph,
)


# ---------------------------------------------------------------------------
# Valid DAGs — should raise nothing
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_valid_linear_chain():
    """Linear chain T1->T2->T3 is valid."""
    tasks = [
        {"id": "T1", "depends_on": []},
        {"id": "T2", "depends_on": ["T1"]},
        {"id": "T3", "depends_on": ["T2"]},
    ]
    validate_task_graph(tasks)  # must not raise


@pytest.mark.unit
def test_valid_parallel_branches():
    """T2 and T3 both depend on T1 — valid diamond pattern."""
    tasks = [
        {"id": "T1", "depends_on": []},
        {"id": "T2", "depends_on": ["T1"]},
        {"id": "T3", "depends_on": ["T1"]},
        {"id": "T4", "depends_on": ["T2", "T3"]},
    ]
    validate_task_graph(tasks)


@pytest.mark.unit
def test_valid_no_dependencies():
    """All tasks independent — valid."""
    tasks = [
        {"id": "T1", "depends_on": []},
        {"id": "T2", "depends_on": []},
        {"id": "T3", "depends_on": []},
    ]
    validate_task_graph(tasks)


@pytest.mark.unit
def test_valid_complex_dag():
    """Complex DAG with fan-in and fan-out — valid."""
    tasks = [
        {"id": "A", "depends_on": []},
        {"id": "B", "depends_on": ["A"]},
        {"id": "C", "depends_on": ["A"]},
        {"id": "D", "depends_on": ["B", "C"]},
        {"id": "E", "depends_on": ["D"]},
        {"id": "F", "depends_on": ["D"]},
        {"id": "G", "depends_on": ["E", "F"]},
    ]
    validate_task_graph(tasks)


@pytest.mark.unit
def test_valid_explicit_empty_depends_on():
    """Tasks with empty depends_on list — valid."""
    tasks = [
        {"id": "T1", "depends_on": []},
        {"id": "T2", "depends_on": []},
    ]
    validate_task_graph(tasks)


@pytest.mark.unit
def test_valid_missing_depends_on_field():
    """Tasks without a depends_on key default to [] — valid."""
    tasks = [
        {"id": "T1"},          # no depends_on at all
        {"id": "T2", "depends_on": ["T1"]},
    ]
    validate_task_graph(tasks)


@pytest.mark.unit
def test_valid_within_max_depth():
    """Depth exactly at max_depth is allowed."""
    # Chain of depth 5
    tasks = [{"id": f"T{i}", "depends_on": [f"T{i-1}"] if i > 0 else []} for i in range(5)]
    validate_task_graph(tasks, max_depth=5)  # exact limit — passes


@pytest.mark.unit
def test_valid_empty_task_list():
    """Empty task list — trivially valid (no graph to validate)."""
    validate_task_graph([])


@pytest.mark.unit
def test_valid_single_task():
    """Single task with no dependencies is valid."""
    validate_task_graph([{"id": "T1", "depends_on": []}])


# ---------------------------------------------------------------------------
# Duplicate IDs — rejected before anything else
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_reject_duplicate_ids_two_tasks():
    """Two tasks with the same ID are rejected."""
    tasks = [
        {"id": "T1", "depends_on": []},
        {"id": "T1", "depends_on": []},   # duplicate
    ]
    with pytest.raises(DuplicateTaskIdError) as exc_info:
        validate_task_graph(tasks)
    assert exc_info.value.task_id == "T1"
    assert exc_info.value.count == 2


@pytest.mark.unit
def test_reject_duplicate_ids_three_tasks():
    """Three tasks with the same ID are rejected."""
    tasks = [
        {"id": "X", "depends_on": []},
        {"id": "X", "depends_on": []},
        {"id": "X", "depends_on": []},
    ]
    with pytest.raises(DuplicateTaskIdError) as exc_info:
        validate_task_graph(tasks)
    assert exc_info.value.task_id == "X"
    assert exc_info.value.count == 3


@pytest.mark.unit
def test_reject_duplicate_ids_non_adjacent():
    """Duplicate ID appears as first and last task."""
    tasks = [
        {"id": "T1", "depends_on": []},
        {"id": "T2", "depends_on": []},
        {"id": "T1", "depends_on": []},
    ]
    with pytest.raises(DuplicateTaskIdError):
        validate_task_graph(tasks)


@pytest.mark.unit
def test_reject_duplicate_ids_complex_graph():
    """Duplicate ID in a complex graph — caught at step 1, before depth check."""
    tasks = [
        {"id": "A", "depends_on": []},
        {"id": "B", "depends_on": ["A"]},
        {"id": "C", "depends_on": ["B"]},
        {"id": "B", "depends_on": ["C"]},   # duplicate B
    ]
    with pytest.raises(DuplicateTaskIdError):
        validate_task_graph(tasks)


# ---------------------------------------------------------------------------
# Dangling dependencies — rejected if all IDs are unique
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_reject_dangling_dependency():
    """Task depends on a non-existent ID."""
    tasks = [
        {"id": "T1", "depends_on": []},
        {"id": "T2", "depends_on": ["T1", "NONEXISTENT"]},
    ]
    with pytest.raises(DanglingDependencyError) as exc_info:
        validate_task_graph(tasks)
    assert exc_info.value.task_id == "T2"
    assert exc_info.value.missing_id == "NONEXISTENT"


@pytest.mark.unit
def test_reject_dangling_self_reference():
    """Self-reference is a cycle, not a dangling dep — CycleError is raised."""
    tasks = [
        {"id": "SELF", "depends_on": ["SELF"]},
    ]
    with pytest.raises(CycleError):
        validate_task_graph(tasks)


@pytest.mark.unit
def test_reject_dangling_partial_depends():
    """One valid dep, one dangling — dangling wins."""
    tasks = [
        {"id": "T1", "depends_on": []},
        {"id": "T2", "depends_on": ["T1", "MISSING"]},
        {"id": "T3", "depends_on": ["T2"]},
    ]
    with pytest.raises(DanglingDependencyError) as exc_info:
        validate_task_graph(tasks)
    assert exc_info.value.task_id == "T2"
    assert exc_info.value.missing_id == "MISSING"


@pytest.mark.unit
def test_reject_dangling_first_task():
    """First task in list depends on non-existent ID."""
    tasks = [
        {"id": "FIRST", "depends_on": ["GHOST"]},
        {"id": "SECOND", "depends_on": ["FIRST"]},
    ]
    with pytest.raises(DanglingDependencyError):
        validate_task_graph(tasks)


# ---------------------------------------------------------------------------
# Cycles — rejected when IDs are unique and all deps exist
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_reject_cycle_two_nodes():
    """T1 -> T2 -> T1 is a cycle."""
    tasks = [
        {"id": "T1", "depends_on": ["T2"]},
        {"id": "T2", "depends_on": ["T1"]},
    ]
    with pytest.raises(CycleError) as exc_info:
        validate_task_graph(tasks)
    # The cycle path should contain both T1 and T2
    assert "T1" in exc_info.value.cycle
    assert "T2" in exc_info.value.cycle


@pytest.mark.unit
def test_reject_cycle_three_nodes():
    """T1 -> T2 -> T3 -> T1 is a cycle."""
    tasks = [
        {"id": "T1", "depends_on": ["T2"]},
        {"id": "T2", "depends_on": ["T3"]},
        {"id": "T3", "depends_on": ["T1"]},
    ]
    with pytest.raises(CycleError) as exc_info:
        validate_task_graph(tasks)
    assert set(exc_info.value.cycle) == {"T1", "T2", "T3"}


@pytest.mark.unit
def test_reject_cycle_self_loop():
    """T1 -> T1 is a self-loop cycle."""
    tasks = [
        {"id": "LOOP", "depends_on": ["LOOP"]},
    ]
    with pytest.raises(CycleError):
        validate_task_graph(tasks)


@pytest.mark.unit
def test_reject_cycle_long_chain():
    """Long chain T1->T2->T3->T4->T5->T1 is rejected."""
    tasks = [
        {"id": "A", "depends_on": ["B"]},
        {"id": "B", "depends_on": ["C"]},
        {"id": "C", "depends_on": ["D"]},
        {"id": "D", "depends_on": ["E"]},
        {"id": "E", "depends_on": ["A"]},
    ]
    with pytest.raises(CycleError):
        validate_task_graph(tasks)


@pytest.mark.unit
def test_reject_cycle_complex_dag_with_cycle():
    """Complex DAG that also contains a cycle — cycle is detected."""
    tasks = [
        {"id": "A", "depends_on": []},
        {"id": "B", "depends_on": ["A"]},
        {"id": "C", "depends_on": ["B"]},
        {"id": "D", "depends_on": ["C"]},
        {"id": "E", "depends_on": ["D"]},
        # Create a cycle: B depends on E (which depends on ... which depends on B)
        {"id": "B", "depends_on": ["E"]},  # duplicate B — caught first as duplicate
    ]
    # B appears twice → DuplicateTaskIdError fires before cycle check
    with pytest.raises(DuplicateTaskIdError):
        validate_task_graph(tasks)


# ---------------------------------------------------------------------------
# Depth exceeded — rejected when graph is acyclic
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_reject_depth_exceeds_max_linear():
    """Linear chain of depth 11 exceeds max_depth=10."""
    tasks = [
        {"id": f"T{i}", "depends_on": [f"T{i-1}"] if i > 0 else []}
        for i in range(11)
    ]
    with pytest.raises(DepthExceededError) as exc_info:
        validate_task_graph(tasks, max_depth=10)
    assert exc_info.value.max_depth == 10
    assert exc_info.value.actual_depth == 11


@pytest.mark.unit
def test_reject_depth_exceeds_max_fan_in():
    """Fan-in increases depth — T3 depends on T1+T2 where T1 is depth 5."""
    tasks = [{"id": f"T{i}", "depends_on": [f"T{i-1}"] if i > 0 else []} for i in range(5)]
    tasks.append({"id": "T20", "depends_on": ["T4"]})   # depth 6
    with pytest.raises(DepthExceededError) as exc_info:
        validate_task_graph(tasks, max_depth=5)
    assert exc_info.value.actual_depth == 6


@pytest.mark.unit
def test_reject_depth_exactly_at_limit_passes():
    """Depth exactly equal to max_depth should pass."""
    tasks = [{"id": f"T{i}", "depends_on": [f"T{i-1}"] if i > 0 else []} for i in range(10)]
    validate_task_graph(tasks, max_depth=10)  # exact limit — allowed


@pytest.mark.unit
def test_reject_depth_one_over():
    """Depth one over the limit is rejected."""
    tasks = [{"id": f"T{i}", "depends_on": [f"T{i-1}"] if i > 0 else []} for i in range(6)]
    with pytest.raises(DepthExceededError):
        validate_task_graph(tasks, max_depth=5)


@pytest.mark.unit
def test_reject_depth_wide_dag():
    """Wide DAG where longest path determines depth."""
    tasks = [
        # Path of length 3
        {"id": "A0", "depends_on": []},
        {"id": "A1", "depends_on": ["A0"]},
        {"id": "A2", "depends_on": ["A1"]},
        {"id": "A3", "depends_on": ["A2"]},  # depth 4
        # Independent parallel branch — not the longest
        {"id": "B0", "depends_on": []},
    ]
    with pytest.raises(DepthExceededError):
        validate_task_graph(tasks, max_depth=3)


# ---------------------------------------------------------------------------
# Edge cases
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_missing_id_field():
    """Task without 'id' field has None as ID; two such tasks raise DuplicateTaskIdError."""
    tasks = [
        {"depends_on": []},   # no 'id' -> id=None
        {"id": "T2", "depends_on": []},
        {"depends_on": []},   # second no-id -> duplicate None
    ]
    with pytest.raises(DuplicateTaskIdError):
        validate_task_graph(tasks)


@pytest.mark.unit
def test_all_tasks_same_id():
    """All 5 tasks share the same ID — one DuplicateTaskIdError."""
    tasks = [{"id": "SAME", "depends_on": []} for _ in range(5)]
    with pytest.raises(DuplicateTaskIdError) as exc_info:
        validate_task_graph(tasks)
    assert exc_info.value.task_id == "SAME"
    assert exc_info.value.count == 5


@pytest.mark.unit
def test_cycle_error_message_contains_path():
    """CycleError message includes the cycle path."""
    tasks = [
        {"id": "A", "depends_on": ["B"]},
        {"id": "B", "depends_on": ["A"]},
    ]
    with pytest.raises(CycleError) as exc_info:
        validate_task_graph(tasks)
    msg = str(exc_info.value)
    assert "A" in msg
    assert "B" in msg
    assert "cycle" in msg.lower()


@pytest.mark.unit
def test_dangling_error_message_contains_task_and_missing():
    """DanglingDependencyError message names both task and missing ID."""
    tasks = [
        {"id": "T1", "depends_on": []},
        {"id": "T2", "depends_on": ["GHOST"]},
    ]
    with pytest.raises(DanglingDependencyError) as exc_info:
        validate_task_graph(tasks)
    msg = str(exc_info.value)
    assert "T2" in msg
    assert "GHOST" in msg


@pytest.mark.unit
def test_duplicate_error_message_contains_count():
    """DuplicateTaskIdError message includes the count."""
    tasks = [
        {"id": "DUP", "depends_on": []},
        {"id": "DUP", "depends_on": []},
    ]
    with pytest.raises(DuplicateTaskIdError) as exc_info:
        validate_task_graph(tasks)
    msg = str(exc_info.value)
    assert "2" in msg


@pytest.mark.unit
def test_depth_error_message_contains_depths():
    """DepthExceededError message shows actual and max depth."""
    tasks = [{"id": f"T{i}", "depends_on": [f"T{i-1}"] if i > 0 else []} for i in range(8)]
    with pytest.raises(DepthExceededError) as exc_info:
        validate_task_graph(tasks, max_depth=5)
    msg = str(exc_info.value)
    assert str(exc_info.value.max_depth) in msg   # max (5)
    assert str(exc_info.value.actual_depth) in msg  # actual (6)


# ---------------------------------------------------------------------------
# Order independence — validation errors fire in deterministic order
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_dangling_before_cycle():
    """Dangling is checked before cycle when both exist in same graph."""
    tasks = [
        {"id": "A", "depends_on": ["GHOST"]},   # dangling
        {"id": "B", "depends_on": ["C"]},
        {"id": "C", "depends_on": ["B"]},        # cycle
    ]
    # IDs unique so far → DanglingDependencyError fires first
    with pytest.raises(DanglingDependencyError):
        validate_task_graph(tasks)


@pytest.mark.unit
def test_cycle_before_depth():
    """Cycle is checked before depth when both exist in same acyclic-but-deep graph."""
    tasks = [
        {"id": "A", "depends_on": ["B"]},
        {"id": "B", "depends_on": ["C"]},
        {"id": "C", "depends_on": ["D"]},
        {"id": "D", "depends_on": ["E"]},
        {"id": "E", "depends_on": ["F"]},
        {"id": "F", "depends_on": ["G"]},
        {"id": "G", "depends_on": ["H"]},
        {"id": "H", "depends_on": ["I"]},
        {"id": "I", "depends_on": ["A"]},  # cycle
    ]
    # IDs unique, no dangle → cycle check fires
    with pytest.raises(CycleError):
        validate_task_graph(tasks, max_depth=3)


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
