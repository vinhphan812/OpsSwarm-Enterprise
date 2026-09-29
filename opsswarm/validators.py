from __future__ import annotations

import yaml
from pathlib import Path
from typing import Any


def _get_skills_dir() -> Path:
    # opsswarm/ is in root/, therefore root is parent of opsswarm/
    return Path(__file__).parent.parent / "skills"


REQUIRED_FIELDS = {"name", "description"}


def load_skill_frontmatter(skill_id: str) -> dict[str, Any] | None:
    """Load and parse SKILL.md frontmatter."""
    skill_path = _get_skills_dir() / skill_id / "SKILL.md"
    if not skill_path.exists():
        return None

    content = skill_path.read_text(encoding="utf-8")

    # Check for YAML frontmatter
    if content.startswith("---"):
        parts = content.split("---", 2)
        if len(parts) >= 3:
            try:
                return yaml.safe_load(parts[1])
            except yaml.YAMLError:
                return None

    return {}


def validate_skill_artefact(skill_id: str) -> bool:
    """
    Validate Skill frontmatter against ADR-006 schema (name + description)
    and validate skill dependency references.
    """
    frontmatter = load_skill_frontmatter(skill_id)
    if frontmatter is None:
        return False

    # Check fields (ADR-006 schema requirement)
    if not REQUIRED_FIELDS.issubset(frontmatter.keys()):
        return False

    # Check dependencies
    depends_on = frontmatter.get("depends_on", [])
    for dep in depends_on:
        # Dependency must exist
        if not (_get_skills_dir() / dep / "SKILL.md").exists():
            return False

    return True


# ----------------------------------------------------------------------
# Issue #26 — Task graph validation
# ----------------------------------------------------------------------


class TaskGraphError(Exception):
    """Base exception for task graph validation errors."""

    pass


class DuplicateTaskIdError(TaskGraphError):
    """Raised when two or more tasks share the same ID."""

    def __init__(self, task_id: str, count: int):
        self.task_id = task_id
        self.count = count
        super().__init__(
            f"Duplicate task ID '{task_id}' appears {count} times in the graph"
        )


class DanglingDependencyError(TaskGraphError):
    """Raised when a task depends on a non-existent task ID."""

    def __init__(self, task_id: str, missing_id: str):
        self.task_id = task_id
        self.missing_id = missing_id
        super().__init__(
            f"Task '{task_id}' depends on non-existent task '{missing_id}'"
        )


class CycleError(TaskGraphError):
    """Raised when the task graph contains a cycle."""

    def __init__(self, cycle: list[str]):
        self.cycle = cycle
        super().__init__(
            f"Task graph contains a cycle: {' -> '.join(cycle + [cycle[0]])}"
        )


class DepthExceededError(TaskGraphError):
    """Raised when any path in the task graph exceeds the configured max depth."""

    def __init__(self, max_depth: int, actual_depth: int, task_id: str):
        self.max_depth = max_depth
        self.actual_depth = actual_depth
        self.task_id = task_id
        super().__init__(
            f"Dependency depth {actual_depth} exceeds max depth {max_depth} "
            f"(task '{task_id}')"
        )


def validate_task_graph(
    tasks: list[dict],
    max_depth: int = 20,
) -> None:
    """Validate a task graph before execution.

    Checks applied (in order, first failure wins):
      1. Unique task IDs  -> DuplicateTaskIdError
      2. All depends_on references exist  -> DanglingDependencyError
      3. No cycles  -> CycleError
      4. Max dependency depth not exceeded  -> DepthExceededError

    Args:
        tasks: List of task dicts, each with at least 'id' and 'depends_on'.
        max_depth: Maximum allowed dependency depth (default 20).

    Raises:
        DuplicateTaskIdError: If any task ID appears more than once.
        DanglingDependencyError: If a task's depends_on contains an unknown ID.
        CycleError: If the dependency graph contains a cycle.
        DepthExceededError: If any path exceeds max_depth.
    """
    task_ids = [t.get("id") for t in tasks]
    all_ids: set[str] = set()

    # 1. Unique IDs
    for tid in task_ids:
        if tid in all_ids:
            count = sum(1 for x in task_ids if x == tid)
            raise DuplicateTaskIdError(tid, count)
        all_ids.add(tid)

    # 2. Dangling dependencies
    task_map = {t.get("id"): t for t in tasks}
    for t in tasks:
        for dep in t.get("depends_on", []):
            if dep not in task_map:
                raise DanglingDependencyError(t.get("id", "?"), dep)

    # 3. Cycle detection via DFS
    WHITE, GREY, BLACK = 0, 1, 2

    color: dict[str, int] = {tid: WHITE for tid in all_ids}
    cycle_path: list[str] = []

    def dfs(node: str) -> bool:
        """DFS return True if cycle found; populates cycle_path on success."""
        color[node] = GREY
        cycle_path.append(node)
        for dep in task_map[node].get("depends_on", []):
            if dep not in task_map:
                continue
            if color[dep] == GREY:
                # Cycle found: from 'dep' to current node
                cycle_start = cycle_path.index(dep)
                cycle_path.append(dep)
                raise CycleError(cycle_path[cycle_start:])
            if color[dep] == WHITE:
                if dfs(dep):
                    return True
        cycle_path.pop()
        color[node] = BLACK
        return False

    for tid in all_ids:
        if color[tid] == WHITE:
            if dfs(tid):
                return  # CycleError already raised

    # 4. Max depth check (longest path from any root)
    def longest_depth(node: str, visited: set[str]) -> int:
        deps = task_map[node].get("depends_on", [])
        if not deps:
            return 1
        max_child = 0
        for dep in deps:
            if dep in visited:
                continue
            child_depth = longest_depth(dep, visited | {node})
            max_child = max(max_child, child_depth)
        return max_child + 1

    for tid in all_ids:
        depth = longest_depth(tid, set())
        if depth > max_depth:
            raise DepthExceededError(max_depth, depth, tid)
