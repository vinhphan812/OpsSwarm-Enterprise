from __future__ import annotations

import asyncio
import uuid

from . import skill_logic as S
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
from .reconciliation import ReconciliationManager
from .store import RunStore

logger = logging.getLogger(__name__)


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

    async def _save(self, run, kind, payload):
        eid, is_dup = self.ev.append(run.run_id, kind, payload)
        if is_dup:
            logger.debug(f"Duplicate evidence skipped: kind={kind}")
        else:
            logger.debug(f"Evidence saved: kind={kind}, eid={eid}")
        self.store.save(run)

    async def _set_state(self, run: RunRecord, state: RunState):
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

    async def start_issue(self, number: int, delivery_id: str | None = None) -> RunRecord:
        lock = self._locks.setdefault(number, asyncio.Lock())
        async with lock:
            existing = self.runs.get(number)
            # Check idempotency: skip if this delivery was already processed
            if existing and delivery_id and delivery_id in existing.idempotency_keys:
                logger.info(f"Skipping duplicate webhook delivery {delivery_id} for issue #{number}")
                return existing
            if existing and existing.state not in {RunState.FAILED, RunState.ABORTED}: return existing
            issue = await self.github.get_issue(number)
            req = self.cfg.get("required_issue_label", "opsswarm")
            names = [x.get("name", "") for x in issue.get("labels", []) if isinstance(x, dict)]
            if req and req not in names: raise RuntimeError(f"Issue #{number} lacks required label {req}")
            run = RunRecord(run_id=f"RUN-GH-{number}-{uuid.uuid4().hex[:8]}", issue_number=number)
            # Store delivery ID for idempotency if provided
            if delivery_id:
                run.idempotency_keys.add(delivery_id)
            self.runs[number] = run;
            await self._set_state(run, RunState.TRIAGE)
            run.incident = S.parse_issue(number, issue);
            await self._save(run, "S1.incident", run.incident.model_dump())
            await self._investigate(run)
            return run

    async def _investigate(self, run: RunRecord, extra_task: Task | None = None):
        await self._set_state(run, RunState.INVESTIGATING)
        main = self.profile("incident-manager")
        if extra_task:
            run.tasks.append(extra_task)
        elif not run.tasks:
            run.tasks = await S.build_tasks(self.oc, main, run.run_id, run.incident)
            if not run.tasks: raise RuntimeError("S2 produced no investigation tasks")
            await self.github.comment(run.issue_number, investigation_started(run))
            await self._save(run, "S2.task_graph", {"tasks": [t.model_dump() for t in run.tasks]})

        done = {f.task_id for f in run.findings}
        pending = [t for t in run.tasks if t.id not in done]
        # Execute dependency-ready tasks in waves.
        while pending:
            ready = [t for t in pending if all(dep in done for dep in t.depends_on)]
            if not ready: raise RuntimeError("Task graph has unsatisfied/cyclic dependencies")

            async def one(t):
                agent = self.profile(t.profile);
                t.status = "RUNNING";
                self.store.save(run)
                try:
                    f = await S.execute_task(self.oc, agent, run.run_id, run.incident, t);
                    t.status = "DONE";
                    return f
                except Exception:
                    t.status = "FAILED";
                    raise

            results = await asyncio.gather(*(one(t) for t in ready))
            for f in results:
                run.findings.append(f);
                done.add(f.task_id);
                await self._save(run, "S4.finding", f.model_dump())
            pending = [t for t in pending if t.id not in done]

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
            await self._set_state(run, RunState.WAITING_INPUT);
            await self.github.comment(run.issue_number, decision_request(run));
            return
        await self._plan(run)

    async def _plan(self, run: RunRecord):
        await self._set_state(run, RunState.PLANNING)
        main = self.profile("incident-manager")
        run.recovery_plan = await S.make_recovery_plan(self.oc, main, run.run_id, run.incident, run.root_cause,
                                                       run.human_inputs)
        await self._save(run, "S3.recovery_plan", run.recovery_plan.model_dump())
        action, reason = self.policy.classify_plan(run.recovery_plan)
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
        await self.github.comment(run.issue_number, f"## OpsSwarm — Failed\n\n{reason}")

    async def _execute_option(self, run: RunRecord, option: RemediationOption):
        # Checkpoint before execution
        self.ev.checkpoint(run.run_id, CheckpointType.EXECUTION, {
            "phase": "pre_execution",
            "option_id": option.id,
            "state": RunState.EXECUTING.value,
        })
        await self._set_state(run, RunState.EXECUTING)
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
            run.decision = DecisionRequest(id=f"DEC-{run.issue_number}-{uuid.uuid4().hex[:6]}", kind="DECISION",
                                           reason="The write outcome is ambiguous. Blind retry is prohibited.",
                                           options=[],
                                           question="Use /opsswarm investigate <read-only verification request>, /opsswarm abort, or /opsswarm resume after external confirmation.")
            await self._set_state(run, RunState.WAITING_DECISION);
            await self.github.comment(run.issue_number, decision_request(run));
            return
        if not run.execution.success:
            run.error = run.execution.summary;
            await self._set_state(run, RunState.FAILED);
            await self.github.comment(run.issue_number, f"## OpsSwarm — Recovery failed\n\n{run.execution.summary}");
            return
        await self._verify(run)

    async def _verify(self, run: RunRecord):
        await self._set_state(run, RunState.VERIFYING)
        run.verification = await S.verify_recovery(self.oc, self.profile("observability-investigator"), run.run_id,
                                                   run.incident, run.execution)
        await self._save(run, "S7.verification", run.verification.model_dump())
        threshold = float(self.cfg.get("verification_confidence_threshold", 0.85))
        if not run.verification.verified or run.verification.confidence < threshold:
            # S7 veto: allow abort instead of fail
            if run.verification.abort:
                run.error = "Verification failed; aborted by S7"
                await self._set_state(run, RunState.ABORTED)
                await self.github.comment(run.issue_number,
                                          f"## OpsSwarm — Verification failed\n\n{run.verification.summary}\n\nAborted by S7 (veto).");
                return
            run.error = "Independent recovery verification failed or confidence below threshold";
            await self._set_state(run, RunState.FAILED)
            await self.github.comment(run.issue_number,
                                      f"## OpsSwarm — Verification failed\n\n{run.verification.summary}\n\nIssue remains open.");
            return
        await self._set_state(run, RunState.RESOLVED);
        await self.github.comment(run.issue_number, resolved(run));
        await self.github.comment(run.issue_number, postmortem(run))
        if self.cfg.get("create_corrective_issues", True) and run.root_cause:
            for action in run.root_cause.corrective_actions:
                await self.github.create_issue(f"[OpsSwarm corrective] {action[:100]}",
                                               f"Parent incident: #{run.issue_number}\n\n{action}",
                                               ["opsswarm:corrective-action"])
        await self.github.close_issue(run.issue_number)

    async def handle_comment(self, number: int, actor: str, body: str, permission: str, command,
                             comment_id: str | None = None, delivery_id: str | None = None):
        run = self.runs.get(number)
        if not run: return
        # Check terminal state: reject all commands if run is in terminal state
        if run.state in TERMINAL_STATES and command.name != "resume":
            logger.info(f"Rejecting command for issue #{number}: run is in terminal state {run.state.value}")
            await self.github.comment(number,
                                      f"OpsSwarm cannot process commands on a closed incident (state: {run.state.value}). Please open a new issue if needed.")
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
            elif outcome == CommandOutcome.RECEIVED.value or outcome == CommandOutcome.EXECUTING.value or outcome == CommandOutcome.UNKNOWN.value:
                # Command was received but not confirmed - can retry safely
                logger.info(f"Resuming incomplete command {comment_id} (outcome: {outcome}) for issue #{number}")

        if delivery_id and delivery_id in run.idempotency_keys:
            logger.info(f"Skipping duplicate webhook delivery {delivery_id} for issue #{number}")
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
            if self.policy.action(option.risk) == "DENY": raise PermissionError(
                "Policy denies this option regardless of human approval")
            if run.decision: run.decision.status = "ANSWERED"
            await self._save(run, "human.approval", {"actor": actor, "option": option.id, "permission": permission})
            await self._execute_option(run, option)
            # Mark command as executed (after execution completes)
            if comment_id:
                run.mark_command_confirmed(comment_id)
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
