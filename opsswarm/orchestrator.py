from __future__ import annotations

import asyncio
import logging
import time
import uuid
from typing import Any

from . import skill_logic as S
from .config import get_budget, get_concurrency, get_tool_allowlist, get_openclaw
from .tool_allowlist import ToolAllowlist
from .errors import new_correlation_id, sanitize_for_comment, sanitize_for_log
from .evidence import EvidenceStore
from .markdown import (
    decision_request,
    diagnosis,
    investigation_started,
    postmortem,
    resolved,
)
from .models import *
from .models import CommandOutcome  # Import for Issue #9 fix
from .policy import PolicyEngine
from .metrics import metrics
from .reconciliation import ReconciliationManager
from .store import RunStore
from .validators import validate_task_graph, TaskGraphError

logger = logging.getLogger(__name__)

# Human-gate states whose wait duration is tracked as G1 (Issue #30)
HUMAN_GATE_STATES: set[RunState] = {
    RunState.WAITING_APPROVAL,
    RunState.WAITING_DECISION,
    RunState.WAITING_INPUT,
}


class RunBudget:
    """Per-run counters with fail-closed limits."""

    def __init__(self, run_id: str, max_tasks: int, max_openclaw_calls: int,
                 max_wall_clock_seconds: float, max_corrective_actions: int,
                 max_depth: int, max_token_budget: int = 1_000_000,
                 max_steps_per_agent: int = 50):
        self.run_id = run_id
        self.max_tasks = max_tasks
        self.max_openclaw_calls = max_openclaw_calls
        self.max_wall_clock_seconds = max_wall_clock_seconds
        self.max_corrective_actions = max_corrective_actions
        self.max_depth = max_depth
        self.max_token_budget = max_token_budget
        self.max_steps_per_agent = max_steps_per_agent
        self.tasks_executed = 0
        self.openclaw_calls = 0
        self.wall_clock_seconds = 0.0
        self.corrective_actions = 0
        self.tokens_used = 0
        self._agent_steps: dict[str, int] = {}  # agent -> steps
        self._start_time = time.monotonic()

    def mark_task(self):
        self.tasks_executed += 1

    def mark_openclaw_call(self):
        self.openclaw_calls += 1

    def mark_corrective_action(self):
        self.corrective_actions += 1

    def mark_tokens(self, tokens: int):
        """Record token usage (input + output combined)."""
        self.tokens_used += tokens

    def mark_agent_step(self, agent: str):
        """Record an agentic step for a specific agent."""
        self._agent_steps[agent] = self._agent_steps.get(agent, 0) + 1

    def agent_steps(self, agent: str) -> int:
        """Return step count for a specific agent."""
        return self._agent_steps.get(agent, 0)

    def snapshot(self) -> dict:
        return {
            "run_id": self.run_id, "tasks_executed": self.tasks_executed,
            "max_tasks": self.max_tasks, "openclaw_calls": self.openclaw_calls,
            "max_openclaw_calls": self.max_openclaw_calls,
            "wall_clock_seconds": round(self.wall_clock_seconds, 2),
            "max_wall_clock_seconds": self.max_wall_clock_seconds,
            "corrective_actions": self.corrective_actions,
            "max_corrective_actions": self.max_corrective_actions,
            "tokens_used": self.tokens_used,
            "max_token_budget": self.max_token_budget,
            "agent_steps": dict(self._agent_steps),
            "max_steps_per_agent": self.max_steps_per_agent,
        }

    def check(self) -> tuple[bool, str | None]:
        checks = ((self.tasks_executed, self.max_tasks, "max_tasks"),
                  (self.openclaw_calls, self.max_openclaw_calls, "max_openclaw_calls"),
                  (self.wall_clock_seconds, self.max_wall_clock_seconds, "max_wall_clock_seconds"),
                  (self.corrective_actions, self.max_corrective_actions, "max_corrective_actions"),
                  (self.tokens_used, self.max_token_budget, "max_token_budget"))
        for current, limit, name in checks:
            if current >= limit:
                return True, f"{name} ({limit}) exceeded"
        # Check per-agent step budget
        for agent, steps in self._agent_steps.items():
            if steps >= self.max_steps_per_agent:
                return True, f"max_steps_per_agent ({self.max_steps_per_agent}) exceeded for {agent}"
        return False, None

    def check_agent_steps(self, agent: str) -> tuple[bool, str | None]:
        """Check step budget for a specific agent."""
        steps = self.agent_steps(agent)
        if steps >= self.max_steps_per_agent:
            return True, f"max_steps_per_agent ({self.max_steps_per_agent}) exceeded for {agent}"
        return False, None

    def elapsed_seconds(self) -> float:
        return time.monotonic() - self._start_time


class ConcurrencyLimiter:
    """Run-scoped semaphore for specialist calls."""

    def __init__(self, run_id: str, max_parallel: int):
        self.run_id = run_id
        self._semaphore = asyncio.Semaphore(max(1, max_parallel))

    async def acquire(self):
        await self._semaphore.acquire()

    def release(self):
        self._semaphore.release()

    @property
    def available(self) -> int:
        return self._semaphore._value  # type: ignore[attr-defined]


class Orchestrator:
    def __init__(self, cfg: dict, github, openclaw, data_dir="runtime-data", enable_recovery: bool = True):
        self.cfg = cfg;
        self.github = github;
        self.oc = openclaw;
        self.store = RunStore(data_dir);
        self.ev = EvidenceStore(data_dir);
        self.policy = PolicyEngine(cfg)
        self.reconciliation = ReconciliationManager(data_dir)
        self.runs = {r.issue_number: r for r in self.store.load_all()}
        self._locks: dict[int, asyncio.Lock] = {}
        # Get state enforcement mode from config (default: audit)
        self.state_enforcement = cfg.get("state_enforcement", "audit")

        # Issue #27: load and inject tool allowlist into the OpenClaw client
        self._tool_allowlist: ToolAllowlist | None = None
        allowlist_cfg = get_tool_allowlist(cfg)
        if allowlist_cfg.get("enabled", False):
            self._tool_allowlist = ToolAllowlist.from_config(cfg)
            if self._tool_allowlist is not None:
                self.oc.set_tool_allowlist(self._tool_allowlist)
                # ADR-027 Fix B: propagate check_tools flag to the client so
                # _check_tool_access() actually raises instead of no-op.
                # Must set check_tools BEFORE set_tool_allowlist so the
                # enforcement gate is active when set_tool_allowlist is called.
                check_tools = get_openclaw(cfg).get("check_tools", False)
                self.oc.set_check_tools(check_tools)
                logger.info(
                    "[ADR-027] Tool allowlist enabled (check_tools=%s, profiles=%s)",
                    check_tools,
                    self._tool_allowlist.profile_names(),
                )
            else:
                logger.warning("[ADR-027] Tool allowlist enabled but failed to load — all tools permitted")
        else:
            logger.debug("[ADR-027] Tool allowlist is disabled in config — all tools permitted")

        budget_cfg = get_budget(cfg)
        self.budget = RunBudget("", budget_cfg["max_tasks_per_run"], budget_cfg["max_openclaw_calls"],
                                budget_cfg["max_wall_clock_seconds"], budget_cfg["max_corrective_actions"],
                                budget_cfg["max_dependency_depth"],
                                budget_cfg.get("max_token_budget", 1_000_000),
                                budget_cfg.get("max_steps_per_agent", 50))
        self._max_parallel = get_concurrency(cfg)["max_parallel_specialists"]
        self._active_budgets: dict[str, RunBudget] = {}
        self._command_locks: dict[int, asyncio.Lock] = {}

        # Run crash recovery on startup if enabled
        if enable_recovery:
            self._recover_runs()

    def _recover_runs(self) -> None:
        """Recover non-terminal runs on startup.

        Loads all non-terminal runs and attempts to recover them from
        checkpoints or evidence logs. This enables crash recovery after
        unexpected shutdowns.
        """
        logger.info("Starting run recovery on startup...")

        non_terminal_runs = self.reconciliation.load_non_terminal_runs()

        if not non_terminal_runs:
            logger.info("No non-terminal runs to recover")
            return

        recovered_count = 0
        for nr in non_terminal_runs:
            # Get the exact instance from self.runs
            run = self.runs.get(nr.issue_number)
            if not run: # Should not happen
                run = nr

            # Check for commands in crash window (EXECUTING -> UNKNOWN)
            changed = False
            for cmd_id, outcome in run.command_outcomes.items():
                if outcome == CommandOutcome.EXECUTING.value:
                    logger.warning(f"Run {run.run_id}: found command {cmd_id} in EXECUTING state. Marking UNKNOWN (crash window).")
                    run.mark_command_unknown(cmd_id)
                    changed = True
            if changed:
                self.store.save(run)

            recovery_result = self.reconciliation.recover_run(run)

            if recovery_result.recovered:
                logger.info(
                    f"Recovered run {run.run_id}: {recovery_result.message}"
                )
                recovered_count += 1
            else:
                logger.warning(
                    f"Could not recover run {run.run_id}: {recovery_result.message}"
                )

        logger.info(f"Run recovery complete: {recovered_count}/{len(non_terminal_runs)} runs recovered")

    def get_reconciliation_report(self, issue_number: int) -> dict | None:
        """Get a reconciliation report for a run.

        Args:
            issue_number: The GitHub issue number.

        Returns:
            Reconciliation report dict, or None if run not found.
        """
        run = self.runs.get(issue_number)
        if not run:
            return None

        return self.reconciliation.get_recovery_plan(run)

    def profile(self, name: str) -> str:
        return self.cfg["openclaw"]["profiles"][name]

    @property
    def tool_allowlist(self) -> ToolAllowlist | None:
        """The loaded tool allowlist, or None if not configured/enabled."""
        return self._tool_allowlist

    def tool_allowlist_report(self) -> dict:
        """Return a structured report of all profile allowlists for audit."""
        if self._tool_allowlist is None:
            return {"enabled": False, "profiles": {}}
        profiles = {}
        for name in self._tool_allowlist.profile_names():
            profiles[name] = self._tool_allowlist.describe_profile(name)
        return {"enabled": True, "profiles": profiles}

    async def _save(self, run, kind, payload):
        eid, is_dup = self.ev.append(run.run_id, kind, payload)
        if is_dup:
            logger.debug(f"Duplicate evidence skipped: kind={kind}")
        else:
            logger.debug(f"Evidence saved: kind={kind}, eid={eid}")
        self.store.save(run)

    async def _set_state(self, run: RunRecord, state: RunState):
        prev_state = run.state
        prev_time = getattr(run, "_state_entered_at", None)
        now = time.monotonic()

        # ── G1: human-gate wait duration (Issue #30) ─────────────────────────
        # When exiting a gate state, record how long the run spent waiting.
        if prev_state in HUMAN_GATE_STATES and prev_time is not None:
            gate_kind_map = {
                RunState.WAITING_APPROVAL: "approval",
                RunState.WAITING_DECISION: "decision",
                RunState.WAITING_INPUT: "input",
            }
            gate_kind = gate_kind_map.get(prev_state)
            if gate_kind is not None:
                metrics.record_human_gate(gate_kind, now - prev_time)

        if prev_state is not None and prev_time is not None:
            duration = now - prev_time
            metrics.record_transition(prev_state, state, duration)
        run._state_entered_at = now
        run.transition(state, enforcement=self.state_enforcement)
        self.store.save(run)
        # Checkpoint state transition
        self.ev.checkpoint(run.run_id, CheckpointType.STATE_TRANSITION, {"state": state.value})

        cfg = self.cfg.get("labels", {});
        lifecycle = list((cfg.get("lifecycle") or {}).values());
        current = (cfg.get("lifecycle") or {}).get(state.value)
        base = cfg.get("base", ["opsswarm", "incident"]);
        labels = base + ([current] if current else [])
        if run.incident and run.incident.severity.startswith("SEV"):
            labels.append("sev:" + run.incident.severity[3:])
        await self.github.set_labels(run.issue_number, labels)
        # ADR-015: Phase 2 RCA label
        if state == RunState.PLAN_RCA:
            rca_label = cfg.get("rca_label", "phase:rca")
            await self.github.add_label(run.issue_number, rca_label)

    async def _budget_preflight(self, run: RunRecord, budget: RunBudget) -> bool:
        budget.wall_clock_seconds = budget.elapsed_seconds()
        exceeded, reason = budget.check()
        if not exceeded:
            return True
        run.decision = DecisionRequest(id=f"DEC-{run.issue_number}-{uuid.uuid4().hex[:6]}", kind="DECISION",
                                       reason=f"Execution budget exceeded: {reason}",
                                       question="The investigation consumed its full execution budget.")
        await self._set_state(run, RunState.WAITING_DECISION)
        await self.github.comment(run.issue_number, decision_request(run))
        return False

    def _validate_and_enforce_graph(self, run: RunRecord, task_dicts: list[dict]) -> None:
        """Validate task graph and enforce max tasks per incident limit.

        Issue #26: validates cycle, depth, dangling deps, duplicate IDs,
        and the max_tasks graph limit. Raises on any violation.
        """
        # Check max tasks per incident
        budget_cfg = get_budget(self.cfg)
        max_graph_tasks = budget_cfg.get("max_tasks_per_run", 50)
        if len(task_dicts) > max_graph_tasks:
            raise TaskGraphError(
                f"Task graph has {len(task_dicts)} tasks, exceeding max_tasks_per_run ({max_graph_tasks}). "
                "Reduce investigation scope or increase max_tasks_per_run."
            )
        # Delegate cycle/depth/dangling/duplicate checks to validators
        validate_task_graph(task_dicts, max_depth=budget_cfg["max_dependency_depth"])

    def _record_budget_snapshot(self, run: RunRecord, budget: RunBudget) -> None:
        """Save current budget utilisation into the run record for evidence
        and publish to Prometheus gauges.
        """
        run.budget_snapshot = budget.snapshot()
        # Publish utilisation as Prometheus gauges
        metrics.set_budget_utilization("tasks", budget.tasks_executed / max(budget.max_tasks, 1))
        metrics.set_budget_utilization(
            "execution_seconds", budget.wall_clock_seconds / max(budget.max_wall_clock_seconds, 1)
        )
        metrics.set_budget_utilization(
            "openclaw_calls", budget.openclaw_calls / max(budget.max_openclaw_calls, 1)
        )

    def _budget_for(self, run: RunRecord) -> RunBudget:
        if run.run_id not in self._active_budgets:
            self._active_budgets[run.run_id] = RunBudget(
                run.run_id, self.budget.max_tasks, self.budget.max_openclaw_calls,
                self.budget.max_wall_clock_seconds, self.budget.max_corrective_actions,
                self.budget.max_depth, self.budget.max_token_budget,
                self.budget.max_steps_per_agent)
        return self._active_budgets[run.run_id]

    async def start_issue(self, number: int, delivery_id: str | None = None) -> RunRecord:
        lock = self._locks.setdefault(number, asyncio.Lock())
        async with lock:
            existing = self.runs.get(number)
            # Check idempotency: skip if this delivery was already processed
            if existing and delivery_id and delivery_id in existing.idempotency_keys:
                logger.info(f"Skipping duplicate webhook delivery {delivery_id} for issue #{number}")
                metrics.record_webhook_delivery("dedup_skipped")
                return existing
            if existing and existing.state not in {RunState.FAILED, RunState.ABORTED}: return existing
            issue = await self.github.get_issue(number)
            req = self.cfg.get("required_issue_label", "opsswarm")
            names = [x.get("name", "") for x in issue.get("labels", []) if isinstance(x, dict)]
            if req and req not in names:
                metrics.record_webhook_delivery("rejected")
                raise RuntimeError(f"Issue #{number} lacks required label {req}")
            run = RunRecord(run_id=f"RUN-GH-{number}-{uuid.uuid4().hex[:8]}", issue_number=number)
            # Store delivery ID for idempotency if provided
            if delivery_id:
                run.idempotency_keys.add(delivery_id)
            self.runs[number] = run;
            metrics.record_run("started")
            await self._set_state(run, RunState.TRIAGE)
            run.incident = S.parse_issue(number, issue);
            await self._save(run, "S1.incident", run.incident.model_dump())
            await self._investigate(run)
            metrics.record_webhook_delivery("processed")
            return run

    async def _investigate(self, run: RunRecord, extra_task: Task | None = None):
        _t0_investigate = time.monotonic()
        await self._set_state(run, RunState.INVESTIGATING)
        main = self.profile("incident-manager")
        if extra_task:
            run.tasks.append(extra_task)
        elif not run.tasks:
            run.tasks = await S.build_tasks(self.oc, main, run.run_id, run.incident)
            if not run.tasks: raise RuntimeError("S2 produced no investigation tasks")
            await self.github.comment(run.issue_number, investigation_started(run))
            # Issue #26: validate task graph before execution
            task_dicts = [t.model_dump() for t in run.tasks]
            self._validate_and_enforce_graph(run, task_dicts)
            await self._save(run, "S2.task_graph", {"tasks": task_dicts})

        budget = self._budget_for(run)
        budget._start_time = _t0_investigate
        limiter = ConcurrencyLimiter(run.run_id, self._max_parallel)
        done = {f.task_id for f in run.findings}
        pending = [t for t in run.tasks if t.id not in done]
        # Execute dependency-ready tasks in waves.
        while pending:
            ready = [t for t in pending if all(dep in done for dep in t.depends_on)]
            if not ready: raise RuntimeError("Task graph has unsatisfied/cyclic dependencies")

            async def one(t):
                if not await self._budget_preflight(run, budget):
                    return None
                budget.mark_task()
                await limiter.acquire()
                try:
                    agent = self.profile(t.profile)
                    t.status = "RUNNING"
                    self.store.save(run)
                    f = await S.execute_task(self.oc, agent, run.run_id, run.incident, t)
                    budget.mark_openclaw_call()
                    t.status = "DONE"
                    return f
                except Exception:
                    t.status = "FAILED"
                    raise
                finally:
                    limiter.release()

            available = max(0, budget.max_tasks - budget.tasks_executed)
            ready = ready[:available]
            results = await asyncio.gather(*(one(t) for t in ready))
            for f in results:
                if f is not None:
                    run.findings.append(f)
                    done.add(f.task_id)
                    await self._save(run, "S4.finding", f.model_dump())
            self._record_budget_snapshot(run, budget)
            self.store.save(run)
            pending = [t for t in pending if t.id not in done]

        if not await self._budget_preflight(run, budget):
            return
        self._record_budget_snapshot(run, budget)
        budget.mark_openclaw_call()
        run.root_cause = await S.synthesize_root_cause(self.oc, main, run.run_id, run.incident, run.findings,
                                                       run.human_inputs)
        await self._set_state(run, RunState.DIAGNOSED);
        await self._save(run, "RCA.root_cause", run.root_cause.model_dump())
        await self.github.comment(run.issue_number, diagnosis(run))
        rca_threshold = float(self.cfg.get("root_cause_confidence_threshold", 0.80))
        if run.root_cause.status == "uncertain" or run.root_cause.confidence < rca_threshold:
            question = run.root_cause.human_input_question or "Root-cause confidence is below the autonomous threshold. Provide relevant operational/business context, or use `/opsswarm investigate <request>` to request more read-only evidence."
            run.decision = DecisionRequest(id=f"DEC-{run.issue_number}-{uuid.uuid4().hex[:6]}", kind="INPUT",
                                           reason="Root-cause analysis is not sufficiently certain for autonomous remediation",
                                           question=question)
            metrics.record_duration("investigate_seconds", time.monotonic() - _t0_investigate)
            await self._set_state(run, RunState.WAITING_INPUT);
            await self.github.comment(run.issue_number, decision_request(run));
            return
        metrics.record_duration("investigate_seconds", time.monotonic() - _t0_investigate)
        await self._plan(run)

    async def _plan(self, run: RunRecord):
        await self._set_state(run, RunState.PLANNING)
        main = self.profile("incident-manager")
        budget = self._budget_for(run)
        if not await self._budget_preflight(run, budget):
            return
        self._record_budget_snapshot(run, budget)
        budget.mark_openclaw_call()
        run.recovery_plan = await S.make_recovery_plan(self.oc, main, run.run_id, run.incident, run.root_cause,
                                                       run.human_inputs)
        await self._save(run, "S3.recovery_plan", run.recovery_plan.model_dump())
        action, reason = self.policy.classify_plan(run.recovery_plan)
        metrics.record_policy_action(action)
        if action == "AUTO":
            option = run.recovery_plan.options[0];
            await self._execute_option(run, option);
            return
        if action in {"APPROVAL", "DECISION", "INPUT"}:
            kind = {"APPROVAL": "APPROVAL", "DECISION": "DECISION", "INPUT": "INPUT"}[action]
            run.decision = DecisionRequest(id=f"DEC-{run.issue_number}-{uuid.uuid4().hex[:6]}", kind=kind,
                                           reason=reason,
                                           options=run.recovery_plan.options if action != "INPUT" else [],
                                           recommended_option=run.recovery_plan.recommended_option,
                                           question=run.recovery_plan.business_input_question)
            # Checkpoint before human gate
            target_state = {"APPROVAL": RunState.WAITING_APPROVAL, "DECISION": RunState.WAITING_DECISION,
                            "INPUT": RunState.WAITING_INPUT}[action]
            self.ev.checkpoint(run.run_id, CheckpointType.HUMAN_GATE, {
                "state": target_state.value,
                "decision_id": run.decision.id,
                "kind": kind,
            })
            await self._set_state(run, target_state)
            await self._save(run, "S6.human_gate", run.decision.model_dump());
            await self.github.comment(run.issue_number, decision_request(run));
            return
        run.error = reason;
        await self._set_state(run, RunState.FAILED);
        corr_id = new_correlation_id()
        safe_reason = sanitize_for_comment(reason)
        logger.error(f"Plan failed [{corr_id}]: {sanitize_for_log(reason)}")
        await self.github.comment(run.issue_number,
                                 f"## OpsSwarm — Failed\n\n{safe_reason}\n\nRef: {corr_id}")

    async def _execute_option(self, run: RunRecord, option: RemediationOption):
        # Checkpoint before execution
        self.ev.checkpoint(run.run_id, CheckpointType.EXECUTION, {
            "phase": "pre_execution",
            "option_id": option.id,
            "state": RunState.EXECUTING.value,
        })
        await self._set_state(run, RunState.EXECUTING)
        budget = self._budget_for(run)
        if not await self._budget_preflight(run, budget):
            return
        self._record_budget_snapshot(run, budget)
        budget.mark_openclaw_call()
        run.execution = await S.execute_recovery(self.oc, self.profile("recovery-responder"), run.run_id, run.incident,
                                                 run.root_cause, option)
        await self._save(run, "S5.execution", run.execution.model_dump())
        # Checkpoint after execution
        self.ev.checkpoint(run.run_id, CheckpointType.EXECUTION, {
            "phase": "post_execution",
            "option_id": option.id,
            "success": run.execution.success,
            "state": RunState.VERIFYING.value if run.execution.success else run.state.value,
        })
        if run.execution.ambiguous:
            metrics.record_ambiguous_write()
            run.decision = DecisionRequest(id=f"DEC-{run.issue_number}-{uuid.uuid4().hex[:6]}", kind="DECISION",
                                           reason="The write outcome is ambiguous. Blind retry is prohibited.",
                                           options=[],
                                           question="Use /opsswarm investigate <read-only verification request>, /opsswarm abort, or /opsswarm resume after external confirmation.")
            await self._set_state(run, RunState.WAITING_DECISION);
            await self.github.comment(run.issue_number, decision_request(run));
            return
        if not run.execution.success:
            run.error = run.execution.summary;
            metrics.record_run("failed")
            await self._set_state(run, RunState.FAILED);
            corr_id = new_correlation_id()
            safe_summary = sanitize_for_comment(run.execution.summary)
            logger.error(f"Recovery failed [{corr_id}]: {sanitize_for_log(run.execution.summary)}")
            await self.github.comment(run.issue_number,
                                     f"## OpsSwarm — Recovery failed\n\n{safe_summary}\n\nRef: {corr_id}");
            return
        await self._verify(run)

    async def _execute_governed_remediation(
        self,
        run: RunRecord,
        option: RemediationOption,
        *,
        approved_by: str | None = None,
        branch: str | None = None,
        base: str = "main",
    ) -> RemediationExecution:
        """Prepare and merge a governed code/service remediation PR.

        This hook deliberately keeps deployment execution separate: callers may
        invoke it after the human approval gate, then run S5/S7 deployment and
        verification. It provides the auditable branch/PR/CI/merge plumbing
        without coupling the two-phase plan workflow to a deployment platform.
        """
        branch_name = branch or f"opsswarm/{run.issue_number}/{option.id}"
        execution = RemediationExecution(
            option_id=option.id,
            kind=RemediationExecutionKind.OPENCLAW_APPLIED,
            human_approved=approved_by is not None,
            approved_by=approved_by,
        )
        try:
            branch_data = await self.github.create_branch(branch_name, base)
            branch_sha = (branch_data.get("object") or {}).get("sha") if isinstance(branch_data, dict) else None
            execution.branch = BranchRef(name=branch_name, base_ref=base, sha=branch_sha)
            execution.evidence.append(f"branch:{branch_name}")

            pr_data = await self.github.open_pr(
                title=f"fix: governed remediation for issue #{run.issue_number}",
                body=(
                    f"Governed OpsSwarm remediation for issue #{run.issue_number}.\n\n"
                    f"Option: `{option.id}`\n{option.description}"
                ),
                head=branch_name,
                base=base,
                draft=True,
            )
            pr_number = pr_data.get("number") if isinstance(pr_data, dict) else None
            execution.pr = PullRequestRef(
                number=pr_number,
                url=pr_data.get("html_url") if isinstance(pr_data, dict) else None,
                title=pr_data.get("title", "") if isinstance(pr_data, dict) else "",
                body=pr_data.get("body", "") if isinstance(pr_data, dict) else "",
                draft=pr_data.get("draft", True) if isinstance(pr_data, dict) else True,
                state=pr_data.get("state") if isinstance(pr_data, dict) else None,
                mergeable=pr_data.get("mergeable") if isinstance(pr_data, dict) else None,
            )
            execution.evidence.append(f"pr:{pr_number}")

            if pr_number is None:
                raise RuntimeError("GitHub did not return a pull-request number")
            status = await self.github.get_pr_status(pr_number)
            execution.ci_passed = status.get("checks_state") == "success"
            if not execution.ci_passed:
                execution.error = f"PR checks are not passing: {status.get('checks_state', 'unknown')}"
                return execution
            if approved_by is None:
                return execution

            merge_data = await self.github.merge_pr(pr_number, merge_method="squash")
            execution.merged = bool((merge_data or {}).get("merged"))
            if not execution.merged:
                execution.error = "GitHub did not confirm pull-request merge"
            else:
                execution.evidence.append(f"merged:{pr_number}")
            return execution
        except Exception as exc:
            execution.error = str(exc)
            return execution

    async def _save_governed_execution(self, run: RunRecord, execution: RemediationExecution) -> None:
        """Persist governed remediation state and its evidence."""
        run.remediation_execution = execution
        await self._save(run, "S5.governed_remediation", execution.model_dump())

    async def _verify(self, run: RunRecord):
        _t0_verify = time.monotonic()
        await self._set_state(run, RunState.VERIFYING)
        budget = self._budget_for(run)
        if not await self._budget_preflight(run, budget):
            return
        self._record_budget_snapshot(run, budget)
        budget.mark_openclaw_call()
        run.verification = await S.verify_recovery(self.oc, self.profile("observability-investigator"), run.run_id,
                                                   run.incident, run.execution)
        await self._save(run, "S7.verification", run.verification.model_dump())
        metrics.record_verification(run.verification.verified)
        threshold = float(self.cfg.get("verification_confidence_threshold", 0.85))
        if not run.verification.verified or run.verification.confidence < threshold:
            # S7 veto: allow abort instead of fail
            if run.verification.abort:
                run.error = "Verification failed; aborted by S7"
                metrics.record_duration("verify_seconds", time.monotonic() - _t0_verify)
                await self._set_state(run, RunState.ABORTED)
                corr_id = new_correlation_id()
                safe_summary = sanitize_for_comment(run.verification.summary)
                logger.error(f"Verification aborted by S7 [{corr_id}]: {sanitize_for_log(run.verification.summary)}")
                await self.github.comment(run.issue_number,
                                          f"## OpsSwarm — Verification failed\n\n{safe_summary}\n\nRef: {corr_id}\n\nAborted by S7 (veto).");
                return
            run.error = "Independent recovery verification failed or confidence below threshold";
            metrics.record_duration("verify_seconds", time.monotonic() - _t0_verify)
            await self._set_state(run, RunState.FAILED)
            corr_id = new_correlation_id()
            safe_summary = sanitize_for_comment(run.verification.summary)
            logger.error(f"Verification failed [{corr_id}]: {sanitize_for_log(run.verification.summary)}")
            await self.github.comment(run.issue_number,
                                      f"## OpsSwarm — Verification failed\n\n{safe_summary}\n\nRef: {corr_id}\n\nIssue remains open.");
            return
        metrics.record_duration("verify_seconds", time.monotonic() - _t0_verify)
        await self._set_state(run, RunState.RESOLVED);
        metrics.record_run("resolved")
        await self.github.comment(run.issue_number, resolved(run));
        await self.github.close_issue(run.issue_number)
        # ADR-015: kick off Phase 2 RCA (Plan_RCA) after close
        if self.cfg.get("rca_enabled", True):
            await self._plan_rca(run)

    # ADR-015: Phase 2 — deferred RCA synthesis (Plan_RCA)
    async def _plan_rca(self, run: RunRecord) -> None:
        """Execute Phase 2: synthesize structured RCA report after incident resolution.

        Runs after the incident is closed (RESOLVED). Produces a durable RCAReport
        and files corrective-action issues. Budget is independent of Phase 1.
        """
        await self._set_state(run, RunState.PLAN_RCA)
        main = self.profile("incident-manager")
        rca_budget_cfg = self.cfg.get("rca_budget", {})
        # Lightweight RCA budget: capped in wall-clock; token tracking uses the
        # existing RunBudget.mark_openclaw_call() call above (shared counter).
        rca_max_wall = rca_budget_cfg.get("max_wall_clock_seconds", 600)
        rca_t0 = time.monotonic()

        async def rca_budget_ok() -> bool:
            elapsed = time.monotonic() - rca_t0
            if elapsed >= rca_max_wall:
                run.error = "RCA budget exhausted: wall-clock limit reached"
                await self._set_state(run, RunState.ABORTED)
                return False
            return True

        if not await rca_budget_ok():
            return

        budget = self._budget_for(run)
        budget.mark_openclaw_call()
        run.rca_report = await S.synthesize_rca(
            self.oc, main, run.run_id, run.incident, run.root_cause,
            run.findings, run.human_inputs
        )
        run.rca_budget_snapshot = {
            "tokens_used": budget.tokens_used,
            "wall_clock_seconds": round(time.monotonic() - rca_t0, 2),
        }
        await self._save(run, "RCA.rca_report", run.rca_report.model_dump())
        await self._set_state(run, RunState.PLAN_RCA_RESOLVED)
        # File corrective-action issues from the structured report
        if self.cfg.get("create_corrective_issues", True) and run.rca_report:
            for ca in run.rca_report.corrective_actions:
                if not await rca_budget_ok():
                    break
                ca_desc = ca.get("description", "") if isinstance(ca, dict) else str(ca)
                ca_priority = ca.get("priority", "medium") if isinstance(ca, dict) else "medium"
                ca_owner = ca.get("owner") if isinstance(ca, dict) else None
                issue_title = f"[OpsSwarm corrective] {ca_desc[:100]}"
                issue_body = (
                    f"**Priority:** {ca_priority}\n"
                    f"**Owner:** {ca_owner or 'unassigned'}\n"
                    f"**Parent incident:** #{run.issue_number}\n\n"
                    f"{ca_desc}"
                )
                url = await self.github.create_issue(
                    issue_title, issue_body, ["opsswarm:corrective-action"]
                )
                if isinstance(ca, dict):
                    ca["ticket_url"] = url
                    ca["status"] = "filed"
        self.store.save(run)

    async def handle_comment(self, number: int, actor: str, body: str, permission: str, command,
                             comment_id: str | None = None, delivery_id: str | None = None):
        """Process one command under a per-issue lock for first-wins idempotency."""
        lock = self._command_locks.setdefault(number, asyncio.Lock())
        async with lock:
            return await self._handle_comment_unlocked(
                number, actor, body, permission, command, comment_id, delivery_id
            )

    async def _handle_comment_unlocked(self, number: int, actor: str, body: str, permission: str, command,
                                       comment_id: str | None = None, delivery_id: str | None = None):
        run = self.runs.get(number)
        if not run: return
        # Check terminal state: reject all commands if run is in terminal state
        if run.state in TERMINAL_STATES and (command is None or command.name != "resume"):
            logger.info(f"Rejecting command for issue #{number}: run is in terminal state {run.state.value}")
            await self.github.comment(number,
                                      f"OpsSwarm cannot process commands on a closed incident (state: {run.state.value}). Please open a new issue if needed.")
            metrics.record_webhook_delivery("rejected")
            return

        # ADR-015: RESOLVED is not in TERMINAL_STATES (allows PLAN_RCA transition)
        # but freetext input is not meaningful on a closed incident — reject it.
        if run.state == RunState.RESOLVED and command is None:
            logger.info(f"Rejecting freetext on issue #{number}: run is in RESOLVED state")
            await self.github.comment(number,
                                      "OpsSwarm cannot process freetext on a closed incident (state: RESOLVED). Please open a new issue if needed.")
            metrics.record_webhook_delivery("rejected")
            return

        # Migrate legacy executed_commands to command_outcomes for backward compatibility
        # This handles loading of old records that don't have command_outcomes yet
        for cmd_id in run.executed_commands:
            if cmd_id not in run.command_outcomes:
                run.command_outcomes[cmd_id] = CommandOutcome.CONFIRMED.value

        # Check idempotency: skip if this comment was already executed
        # Use command_outcomes for the new durable tracking
        if comment_id and comment_id in run.command_outcomes:
            outcome = run.command_outcomes.get(comment_id)
            if outcome == CommandOutcome.CONFIRMED.value:
                logger.info(f"Skipping already executed comment {comment_id} for issue #{number}")
                return
            elif outcome == CommandOutcome.UNKNOWN.value:
                # ADR-012: UNKNOWN means the external effect may have happened.
                # Blind retry is prohibited; require explicit reconciliation first.
                logger.warning(
                    "Rejecting command %s for issue #%s: outcome is UNKNOWN; "
                    "reconciliation is required before retry",
                    comment_id,
                    number,
                )
                await self.github.comment(
                    number,
                    "OpsSwarm cannot safely retry this command because its external outcome is unknown. "
                    "Reconcile the external system first, then issue a new command.",
                )
                metrics.record_webhook_delivery("rejected")
                return
            elif outcome in (CommandOutcome.RECEIVED.value, CommandOutcome.EXECUTING.value):
                logger.info(f"Resuming incomplete command {comment_id} (outcome: {outcome}) for issue #{number}")

        if delivery_id and delivery_id in run.idempotency_keys:
            logger.info(f"Skipping duplicate webhook delivery {delivery_id} for issue #{number}")
            metrics.record_webhook_delivery("dedup_skipped")
            return

        # Record this comment/delivery as RECEIVED (not yet executed) - Issue #9 fix
        # This is persisted BEFORE execution to enable crash recovery
        if comment_id:
            run.command_outcomes[comment_id] = CommandOutcome.RECEIVED.value
        if delivery_id:
            run.idempotency_keys.add(delivery_id)

        # Persist immediately so crash recovery can find this command
        if comment_id or delivery_id:
            self.store.save(run)
        metrics.record_webhook_delivery("processed")
        if not command:
            run.human_inputs.append({"actor": actor, "text": body, "authority": "information-only"});
            await self._save(run, "human.free_text", run.human_inputs[-1]);
            return
        rank = {"none": 0, "read": 1, "triage": 2, "write": 3, "maintain": 4, "admin": 5}
        min_input = self.cfg.get("human_authority", {}).get("minimum_permission_for_input", "read")
        min_approval = self.cfg.get("human_authority", {}).get("minimum_permission_for_approval", "maintain")
        min_abort = self.cfg.get("human_authority", {}).get("minimum_permission_for_abort", "maintain")

        def require(level):
            if rank.get(permission, 0) < rank.get(level, 99): raise PermissionError(
                f"@{actor} has {permission}; requires {level}")

        if command.name in {"provide", "investigate", "resume"}:
            require(min_input)
        elif command.name in {"approve", "reject"}:
            require(min_approval)
        elif command.name == "abort":
            require(min_abort)
        if command.name == "abort":
            # Mark command as executing
            if comment_id:
                run.mark_command_executing(comment_id)
                self.store.save(run)
            run.error = f"Aborted by @{actor}";
            await self._set_state(run, RunState.ABORTED);
            metrics.record_command("abort")
            await self.github.comment(number, f"## OpsSwarm — Aborted\n\nBy `@{actor}`.")
            # Mark command as executed
            if comment_id:
                run.mark_command_confirmed(comment_id)
                self.store.save(run)
            return
        if command.name == "provide":
            # Mark command as executing
            if comment_id:
                run.mark_command_executing(comment_id)
                self.store.save(run)
            run.human_inputs.append({"actor": actor, "text": command.argument, "authority": "provided-input"});
            run.decision = None;
            await self._save(run, "human.input", run.human_inputs[-1])
            metrics.record_command("provide")
            # Re-synthesize root cause then plan.
            await self._investigate(run)
            # Mark command as executed
            if comment_id:
                run.mark_command_confirmed(comment_id)
                self.store.save(run)
            return
        if command.name == "investigate":
            # Mark command as executing
            if comment_id:
                run.mark_command_executing(comment_id)
                self.store.save(run)
            extra = await S.make_extra_task(self.oc, self.profile("incident-manager"), run.run_id, run.incident,
                                            command.argument)
            # Unique task ID for repeated investigations.
            extra.id = f"HX{len([t for t in run.tasks if t.id.startswith('HX')]) + 1}"
            run.decision = None;
            metrics.record_command("investigate")
            await self._investigate(run, extra_task=extra)
            # Mark command as executed
            if comment_id:
                run.mark_command_confirmed(comment_id)
                self.store.save(run)
            return
        if command.name == "reject":
            # Mark command as executing
            if comment_id:
                run.mark_command_executing(comment_id)
                self.store.save(run)
            if run.decision: run.decision.status = "REJECTED"
            run.error = f"Proposed remediation rejected by @{actor}";
            await self._set_state(run, RunState.WAITING_DECISION);
            metrics.record_command("reject")
            await self.github.comment(number,
                                      "OpsSwarm recorded the rejection. Use `/opsswarm investigate ...`, `/opsswarm provide ...`, or `/opsswarm abort`.")
            # Mark command as executed
            if comment_id:
                run.mark_command_confirmed(comment_id)
                self.store.save(run)
            return
        if command.name == "approve":
            # Mark command as executing
            if comment_id:
                run.mark_command_executing(comment_id)
                self.store.save(run)
            if not run.recovery_plan: raise RuntimeError("No recovery plan exists")
            option = next((o for o in run.recovery_plan.options if o.id == command.argument), None)
            if not option: raise ValueError(f"Unknown option id: {command.argument}")

            # ADR-013: resolve effective risk via trusted registry first.
            # Precedence: registry match (always wins) → classify_operation (escalation only)
            #   → model-supplied label (fallback).
            effective_risk, registry_result, classified_risk = (
                self.policy.resolve_effective_risk_for_option(
                    option.id, option.description, option.risk
                )
            )

            # Record S6.capability_override evidence whenever the registry was consulted.
            # Even when no rule matched, recording the lookup provides an audit trail of
            # what the system considered. We record it only when there was a meaningful
            # override or a non-trivial fallback path.
            if registry_result is not None or classified_risk is not None:
                evidence_payload: dict[str, Any] = {
                    "option_id": option.id,
                    "model_risk": option.risk.value,
                    "effective_risk": effective_risk.value,
                    "option_description": option.description,
                }
                if registry_result is not None:
                    evidence_payload.update({
                        "canonical_operation": registry_result.canonical_operation,
                        "rule_id": registry_result.rule_id,
                        "registry_risk": registry_result.registry_risk.value
                        if registry_result.registry_risk
                        else None,
                        "pattern_matched": registry_result.pattern_matched,
                        "pattern_mode": registry_result.pattern_mode,
                        "approved_by": registry_result.approved_by,
                    })
                else:
                    evidence_payload["classified_risk"] = (
                        classified_risk.value if classified_risk else None
                    )
                await self._save(run, "S6.capability_override", evidence_payload)

            if self.policy.action(effective_risk) == "DENY":
                metrics.record_policy_action("DENY")
                raise PermissionError(
                    "Policy denies this option regardless of human approval "
                    f"(effective risk: {effective_risk.value})"
                )
            if run.decision:
                run.decision.status = "ANSWERED"
            await self._save(run, "human.approval", {"actor": actor, "option": option.id, "permission": permission})
            metrics.record_command("approve")
            await self._execute_option(run, option)
            # Resolve the durable command outcome after the execution attempt.
            # Ambiguous outcomes remain UNKNOWN (set during recovery); a confirmed
            # failure is ABSENT and only a successful execution is CONFIRMED.
            if comment_id and run.execution:
                if run.execution.success and not run.execution.ambiguous:
                    run.mark_command_confirmed(comment_id)
                elif not run.execution.ambiguous:
                    run.mark_command_absent(comment_id)
                else:
                    run.mark_command_unknown(comment_id)
                self.store.save(run)
            return
        if command.name == "resume":
            # Check for valid checkpoint to resume from
            checkpoint = self.ev.get_last_checkpoint(run.run_id)
            if checkpoint:
                checkpoint_type = checkpoint.get("payload", {}).get("checkpoint_type", "unknown")
                checkpoint_state = checkpoint.get("payload", {}).get("state", "unknown")
                logger.info(f"Resuming from checkpoint: type={checkpoint_type}, state={checkpoint_state}")

                # Resume from human gate checkpoint
                if checkpoint_type == CheckpointType.HUMAN_GATE.value:
                    await self.github.comment(number,
                                              f"Resuming from checkpoint (type: {checkpoint_type}, state: {checkpoint_state}). Use `/opsswarm approve <option>` or `/opsswarm provide <input>` to continue.")
                    return

                # Resume from execution checkpoint - verify or retry
                if checkpoint_type == CheckpointType.EXECUTION.value:
                    phase = checkpoint.get("payload", {}).get("phase", "unknown")
                    if phase == "post_execution" and run.execution and run.execution.success:
                        await self._verify(run)
                        return
                    elif phase == "pre_execution":
                        await self.github.comment(number,
                                                  "Resuming from pre-execution checkpoint. Use `/opsswarm approve <option>` to continue execution.")
                        return

                # Resume from state transition checkpoint - continue workflow
                if checkpoint_type == CheckpointType.STATE_TRANSITION.value:
                    if run.state == RunState.INVESTIGATING:
                        await self._investigate(run)
                        return
                    elif run.state == RunState.PLANNING:
                        await self._plan(run)
                        return
                    elif run.state == RunState.EXECUTING and run.execution:
                        await self._verify(run)
                        return

            # Fallback: original behavior
            if run.state == RunState.FAILED and run.execution and run.execution.success:
                await self._verify(run)
            else:
                await self.github.comment(number,
                                          "`/opsswarm resume` is only accepted when a safe checkpoint exists. Use an explicit approve/investigate/provide command.")
