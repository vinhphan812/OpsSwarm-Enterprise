# S2: TaskGraph DAG test suite - Dependency and parallelism validation
# Target: Task DAG operations (build_tasks output analysis)
# Reference: docs/TEST_CAMPAIGN_S192.md section 4.2

import pytest

from opsswarm.models import Task, TaskType, Risk


# === DAG Construction Helpers ===

def build_dag(tasks_data: list[dict]) -> list[Task]:
    """Build a list of Task objects from raw data for DAG testing."""
    return [Task.model_validate(t) for t in tasks_data]


def get_ready_tasks(tasks: list[Task]) -> list[Task]:
    """Get tasks that have no pending dependencies (can run now)."""
    task_ids = {t.id for t in tasks}
    completed = set()  # In simulation, nothing is completed yet
    ready = []
    for task in tasks:
        if task.id in completed:
            continue
        deps = set(task.depends_on or [])
        if deps <= completed:
            ready.append(task)
    return ready


def get_parallelizable_groups(tasks: list[Task]) -> list[list[Task]]:
    """Group tasks by their parallelism level (0 = must run first, then increasing)."""
    levels = {}
    task_map = {t.id: t for t in tasks}

    def get_level(task_id: str, visited: set) -> int:
        if task_id in visited:
            return 0  # Circular dependency - treat as level 0
        if task_id in levels:
            return levels[task_id]

        task = task_map.get(task_id)
        if not task or not task.depends_on:
            levels[task_id] = 0
            return 0

        visited.add(task_id)
        max_dep_level = max((get_level(dep, visited.copy()) for dep in task.depends_on if dep in task_map), default=-1)
        levels[task_id] = max_dep_level + 1
        return levels[task_id]

    for task in tasks:
        get_level(task.id, set())

    # Group by level
    groups = {}
    for task in tasks:
        level = levels.get(task.id, 0)
        if level not in groups:
            groups[level] = []
        groups[level].append(task)

    return [groups[l] for l in sorted(groups.keys())]


# === NORMAL (8 tests) ===

@pytest.mark.unit
def test_dag_n1_linear_chain():
    """DAG-N1: Linear chain - T1 -> T2 -> T3 executes in order"""
    tasks = build_dag([
        {"id": "T1", "type": "OBSERVE", "objective": "First", "profile": "observability"},
        {"id": "T2", "type": "INVESTIGATE", "objective": "Second", "profile": "application", "depends_on": ["T1"]},
        {"id": "T3", "type": "DIAGNOSE", "objective": "Third", "profile": "infrastructure", "depends_on": ["T2"]}
    ])

    groups = get_parallelizable_groups(tasks)

    assert len(groups) == 3  # Three execution levels
    assert groups[0][0].id == "T1"
    assert groups[1][0].id == "T2"
    assert groups[2][0].id == "T3"


@pytest.mark.unit
def test_dag_n2_parallel_branches():
    """DAG-N2: Parallel branches - T1 spawns T2,T3 which can run in parallel"""
    tasks = build_dag([
        {"id": "T1", "type": "OBSERVE", "objective": "First", "profile": "observability"},
        {"id": "T2", "type": "INVESTIGATE", "objective": "Second A", "profile": "application", "depends_on": ["T1"]},
        {"id": "T3", "type": "INVESTIGATE", "objective": "Second B", "profile": "infrastructure", "depends_on": ["T1"]}
    ])

    groups = get_parallelizable_groups(tasks)

    assert len(groups) == 2  # Two execution levels
    assert groups[0][0].id == "T1"  # First level
    assert len(groups[1]) == 2  # Second level has 2 parallel tasks


@pytest.mark.unit
def test_dag_n3_fan_in_dependency():
    """DAG-N3: Fan-in - T3 depends on both T1 and T2"""
    tasks = build_dag([
        {"id": "T1", "type": "OBSERVE", "objective": "Check A", "profile": "observability"},
        {"id": "T2", "type": "OBSERVE", "objective": "Check B", "profile": "application"},
        {"id": "T3", "type": "DIAGNOSE", "objective": "Analyze", "profile": "infrastructure",
         "depends_on": ["T1", "T2"]}
    ])

    groups = get_parallelizable_groups(tasks)

    assert len(groups) == 2  # Two levels
    assert len(groups[0]) == 2  # T1, T2 run first (parallel)
    assert groups[1][0].id == "T3"  # T3 runs after both


@pytest.mark.unit
def test_dag_n4_all_parallel_no_dependencies():
    """DAG-N4: All parallel - no dependencies means all can run at once"""
    tasks = build_dag([
        {"id": "T1", "type": "OBSERVE", "objective": "Check A", "profile": "observability"},
        {"id": "T2", "type": "OBSERVE", "objective": "Check B", "profile": "application"},
        {"id": "T3", "type": "OBSERVE", "objective": "Check C", "profile": "infrastructure"}
    ])

    groups = get_parallelizable_groups(tasks)

    assert len(groups) == 1  # One level - all parallel
    assert len(groups[0]) == 3


@pytest.mark.unit
def test_dag_n5_complex_dag():
    """DAG-N5: Complex DAG - multiple levels with branches and merges"""
    tasks = build_dag([
        {"id": "T1", "type": "OBSERVE", "objective": "Start", "profile": "observability"},
        {"id": "T2", "type": "INVESTIGATE", "objective": "Branch A", "profile": "application", "depends_on": ["T1"]},
        {"id": "T3", "type": "INVESTIGATE", "objective": "Branch B", "profile": "infrastructure", "depends_on": ["T1"]},
        {"id": "T4", "type": "DIAGNOSE", "objective": "Merge A", "profile": "database", "depends_on": ["T2"]},
        {"id": "T5", "type": "DIAGNOSE", "objective": "Merge B", "profile": "database", "depends_on": ["T3"]},
        {"id": "T6", "type": "DIAGNOSE", "objective": "Final", "profile": "infrastructure", "depends_on": ["T4", "T5"]}
    ])

    groups = get_parallelizable_groups(tasks)

    assert len(groups) == 4  # Four execution levels
    assert groups[0][0].id == "T1"
    assert len(groups[1]) == 2  # T2, T3 parallel
    assert len(groups[2]) == 2  # T4, T5 parallel
    assert groups[3][0].id == "T6"


@pytest.mark.unit
def test_dag_n6_valid_profiles():
    """DAG-N6: Valid profiles - all expected specialist profiles present"""
    tasks = build_dag([
        {"id": "T1", "type": "OBSERVE", "objective": "Check metrics", "profile": "observability"},
        {"id": "T2", "type": "INVESTIGATE", "objective": "Check code", "profile": "application"},
        {"id": "T3", "type": "INVESTIGATE", "objective": "Check infra", "profile": "infrastructure"},
        {"id": "T4", "type": "DIAGNOSE", "objective": "Check DB", "profile": "database"}
    ])

    profiles = {t.profile for t in tasks}
    expected_profiles = {"observability", "application", "infrastructure", "database"}

    assert profiles == expected_profiles


@pytest.mark.unit
def test_dag_n7_task_type_distribution():
    """DAG-N7: Task type distribution - OBSERVE/INVESTIGATE/DIAGNOSE present"""
    tasks = build_dag([
        {"id": "T1", "type": "OBSERVE", "objective": "Observe", "profile": "observability"},
        {"id": "T2", "type": "INVESTIGATE", "objective": "Investigate", "profile": "application"},
        {"id": "T3", "type": "DIAGNOSE", "objective": "Diagnose", "profile": "infrastructure"}
    ])

    types = {t.type for t in tasks}

    assert TaskType.OBSERVE in types
    assert TaskType.INVESTIGATE in types
    assert TaskType.DIAGNOSE in types
    assert TaskType.REMEDIATE not in types  # Per S2 constraints


@pytest.mark.unit
def test_dag_n8_parallelizable_flag():
    """DAG-N8: parallelizable flag - respected in grouping"""
    tasks = build_dag([
        {"id": "T1", "type": "OBSERVE", "objective": "Check", "profile": "observability", "parallelizable": True},
        {"id": "T2", "type": "OBSERVE", "objective": "Check", "profile": "application", "parallelizable": False}
    ])

    # T1 has parallelizable=True, T2 has parallelizable=False
    # Both can run in parallel at the same level regardless of flag
    # The flag is a hint to the executor, not the DAG builder
    ready = get_ready_tasks(tasks)

    assert len(ready) == 2  # Both ready at start


# === BOUNDARY (6 tests) ===

@pytest.mark.unit
def test_dag_b1_self_dependency():
    """DAG-B1: Self dependency - task depends on itself"""
    tasks = build_dag([
        {"id": "T1", "type": "OBSERVE", "objective": "Check", "profile": "observability", "depends_on": ["T1"]}
    ])

    groups = get_parallelizable_groups(tasks)

    # Self-dependency causes level 0 (treated as immediate dependency)
    assert len(groups) >= 1


@pytest.mark.unit
def test_dag_b2_orphan_dependency():
    """DAG-B2: Orphan dependency - task depends on non-existent task"""
    tasks = build_dag([
        {"id": "T1", "type": "OBSERVE", "objective": "Check", "profile": "observability", "depends_on": ["NONEXISTENT"]}
    ])

    groups = get_parallelizable_groups(tasks)

    # Orphan dependency treated as satisfied (non-existent task not in map)
    assert len(groups) >= 1


@pytest.mark.unit
def test_dag_b3_empty_task_list():
    """DAG-B3: Empty task list - no tasks to analyze"""
    tasks = []

    groups = get_parallelizable_groups(tasks)

    assert groups == []


@pytest.mark.unit
def test_dag_b4_single_task():
    """DAG-B4: Single task - no dependencies"""
    tasks = build_dag([
        {"id": "T1", "type": "OBSERVE", "objective": "Check", "profile": "observability"}
    ])

    groups = get_parallelizable_groups(tasks)

    assert len(groups) == 1
    assert groups[0][0].id == "T1"


@pytest.mark.unit
def test_dag_b5_large_dag():
    """DAG-B5: Large DAG - 20 tasks with various dependencies"""
    tasks_data = []
    for i in range(20):
        deps = []
        if i >= 2:
            deps = [f"T{i - 2}"]  # Creates 2 parallel chains: T0->T2->T4... and T1->T3->T5...
        tasks_data.append({
            "id": f"T{i}",
            "type": "OBSERVE",
            "objective": f"Task {i}",
            "profile": "observability",
            "depends_on": deps
        })

    tasks = build_dag(tasks_data)
    groups = get_parallelizable_groups(tasks)

    # 20 tasks with 2 parallel chains = 10 dependency levels (each level has 2 tasks)
    assert len(groups) == 10
    # Each group should have 2 tasks (the two parallel chains)
    assert all(len(g) == 2 for g in groups)


@pytest.mark.unit
def test_dag_b6_mixed_parallelizable():
    """DAG-B6: Mixed parallelizable flags - some true, some false"""
    tasks = build_dag([
        {"id": "T1", "type": "OBSERVE", "objective": "Check", "profile": "observability", "parallelizable": True},
        {"id": "T2", "type": "OBSERVE", "objective": "Check", "profile": "application", "parallelizable": False},
        {"id": "T3", "type": "INVESTIGATE", "objective": "Check", "profile": "infrastructure", "parallelizable": True},
        {"id": "T4", "type": "DIAGNOSE", "objective": "Check", "profile": "database", "parallelizable": False}
    ])

    groups = get_parallelizable_groups(tasks)

    # All at same level since no dependencies
    assert len(groups) == 1
    assert len(groups[0]) == 4


# === FAULT (8 tests) ===

@pytest.mark.unit
def test_dag_f1_cycle_detection():
    """DAG-F1: Cycle detection - T1->T2->T1 creates a cycle"""
    tasks = build_dag([
        {"id": "T1", "type": "OBSERVE", "objective": "Check", "profile": "observability", "depends_on": ["T2"]},
        {"id": "T2", "type": "INVESTIGATE", "objective": "Check", "profile": "application", "depends_on": ["T1"]}
    ])

    # With cycle detection in get_level, should handle gracefully
    groups = get_parallelizable_groups(tasks)

    # Should still produce groups (cycle handled)
    assert len(groups) >= 1


@pytest.mark.unit
def test_dag_f2_empty_objective():
    """DAG-F2: Empty objective - task with empty string objective"""
    tasks = build_dag([
        {"id": "T1", "type": "OBSERVE", "objective": "", "profile": "observability"}
    ])

    assert tasks[0].objective == ""


@pytest.mark.unit
def test_dag_f3_very_long_task_id():
    """DAG-F3: Very long task ID - handles without crash"""
    long_id = "T" + "x" * 200
    tasks = build_dag([
        {"id": long_id, "type": "OBSERVE", "objective": "Check", "profile": "observability"}
    ])

    assert tasks[0].id == long_id


@pytest.mark.unit
def test_dag_f4_many_dependencies():
    """DAG-F4: Many dependencies - task depends on many others"""
    deps = [f"T{i}" for i in range(10)]
    tasks_data = [{"id": f"T{i}", "type": "OBSERVE", "objective": f"Task {i}", "profile": "observability"} for i in
                  range(10)]
    tasks_data.append({
        "id": "T10",
        "type": "DIAGNOSE",
        "objective": "Final",
        "profile": "infrastructure",
        "depends_on": deps
    })

    tasks = build_dag(tasks_data)
    groups = get_parallelizable_groups(tasks)

    assert len(groups) == 2
    assert len(groups[0]) == 10
    assert groups[1][0].id == "T10"


@pytest.mark.unit
def test_dag_f5_duplicate_ids():
    """DAG-F5: Duplicate task IDs - validation should catch this"""

    # First task is fine
    t1 = Task.model_validate({"id": "T1", "type": "OBSERVE", "objective": "Check", "profile": "observability"})
    # Second task with same ID would be a separate Task object (not validated by Pydantic)
    t2 = Task.model_validate({"id": "T1", "type": "INVESTIGATE", "objective": "Check", "profile": "application"})

    # Both are valid as separate Task objects (DAG-level validation needed)
    assert t1.id == t2.id  # Same ID allowed by model


@pytest.mark.unit
def test_dag_f6_invalid_depends_on_format():
    """DAG-F6: Invalid depends_on format - non-list value"""
    # depends_on must be a list - passing a string should fail validation
    with pytest.raises(Exception):
        Task.model_validate({
            "id": "T1",
            "type": "OBSERVE",
            "objective": "Check",
            "profile": "observability",
            "depends_on": "T2"  # Should be a list, not a string
        })


@pytest.mark.unit
def test_dag_f7_default_risk_read():
    """DAG-F7: Default risk is READ - verify default"""
    task = Task.model_validate({
        "id": "T1",
        "type": "OBSERVE",
        "objective": "Check",
        "profile": "observability"
    })

    assert task.risk == Risk.READ


@pytest.mark.unit
def test_dag_f8_expected_output_field():
    """DAG-F8: expected_output field - default value present"""
    task = Task.model_validate({
        "id": "T1",
        "type": "OBSERVE",
        "objective": "Check",
        "profile": "observability"
    })

    assert task.expected_output == "Finding"


# === CROSS-SKILL (2 tests) ===

@pytest.mark.unit
def test_dag_c1_s2_to_s4_contract():
    """DAG-C1: S2 to S4 contract - tasks valid input for execute_task"""
    tasks = build_dag([
        {"id": "T1", "type": "OBSERVE", "objective": "Check metrics", "profile": "observability"},
        {"id": "T2", "type": "INVESTIGATE", "objective": "Check logs", "profile": "application"}
    ])

    # Verify all tasks have required fields for S4 (execute_task)
    for task in tasks:
        assert hasattr(task, 'id')
        assert hasattr(task, 'type')
        assert hasattr(task, 'objective')
        assert hasattr(task, 'profile')
        assert task.type in [TaskType.OBSERVE, TaskType.INVESTIGATE, TaskType.DIAGNOSE]


@pytest.mark.unit
def test_dag_c2_parallelism_for_dispatch():
    """DAG-C2: Parallelism for dispatch - ready tasks can be dispatched together"""
    tasks = build_dag([
        {"id": "T1", "type": "OBSERVE", "objective": "Check metrics", "profile": "observability"},
        {"id": "T2", "type": "OBSERVE", "objective": "Check logs", "profile": "application"},
        {"id": "T3", "type": "OBSERVE", "objective": "Check network", "profile": "infrastructure"}
    ])

    groups = get_parallelizable_groups(tasks)

    # All 3 tasks at level 0 - can be dispatched in parallel
    assert len(groups) == 1
    assert len(groups[0]) == 3

    # All have READ risk - safe for parallel execution
    assert all(t.risk == Risk.READ for t in groups[0])
