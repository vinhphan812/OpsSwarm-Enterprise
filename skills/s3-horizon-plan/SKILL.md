---
name: s3-horizon-plan
description: Produce evidence-supported remediation options.
---

# S3 HorizonPlan

## Purpose
The S3 HorizonPlan skill is the strategic planning engine of the incident response suite. Its goal is to synthesize the disparate results of diagnostic tasks from S2 TaskGraph into concrete, actionable RecoveryPlan options. This skill does not act; rather, it proposes. It evaluates the current diagnostic evidence and formulates multiple potential paths forward, carefully classifying each option by its potential impact and operational risk. This structured output gives the human-in-the-loop or downstream S5 CollabExec skill a clear set of options, ranked by likelihood of success and balanced against the operational risk to the business environment.

## Inputs
S3 HorizonPlan requires the full set of investigation results and the original IncidentContext.
- `TaskResults`: A list of execution results (logs, extracted metrics, confirmed diagnoses) from the tasks executed by the diagnostic profiles in S2.
- `IncidentContext`: The original context (Service, Symptoms, Impact) to ensure proposed remediations remain scoped and relevant.
- `RiskConstraintCatalog`: The policy database defining which operations are classified as "destructive" for a given service.
- `EvidenceCorrelationMap`: (optional) Results from cross-task evidence analysis.
These inputs are aggregated by the S8 OrchestrationHub before being passed into the S3 planning engine.

## Outputs
The outputs are encapsulated in a `RecoveryPlan` structure designed for decision-making.
- `RemediationOption[]`: A list of options, ordered by confidence and inversely by risk. Each includes:
  - `description`: The proposed remediation action (e.g., "Rollback to version X").
  - `risk_level` (enum: read, safe_write, risky_write, destructive): Categorization of the action's potential danger.
  - `evidence_link`: Traceable diagnostic findings that support this option.
  - `estimated_impact`: Expected downtime/side-effects.
- `UnknownConstraintsInfo`: A list of data points or policy details that were *not* determined and need clarification before final decision-making.

## Key Rules & Constraints
1. Risk Classification: Every `RemediationOption` MUST be explicitly classified as one of `read`, `safe_write`, `risky_write`, or `destructive`.
2. Evidence Support: Every option must be strictly correlated to evidence produced by S2-executed tasks; NO speculative remediation is permitted.
3. Constraint Surfacing: When the skill cannot determine if a business constraint is violated by a `risky_write` action, it MUST mark the constraint as "UNKNOWN" and surface it in `UnknownConstraintsInfo` rather than guessing.
4. Ranking: Options are ranked primarily by their confidence and secondarily by their `risk_level`.
5. No Automation Overreach: The skill MUST NOT automatically execute `destructive` actions without explicit human approval passed down from the S8 OrchestrationHub.
6. Traceability: Every proposed action must be able to link back to the exact diagnostic findings that justify it.

## Edge Cases
- Conflicting Evidence: If diagnostic tasks produce contradictory results, the skill halts planning and proposes an `OBSERVE` task to clarify instead of remediation.
- Insufficient Evidence: If too few diagnostic tasks are completed, the skill proactively triggers a request for more investigation before formulating a plan.
- Policy Denial: If an option requires a `safe_write` but is denied by current `skill-gates.yml` policy, it is demoted to `risky_write` and flagged.
- Constraint Volatility: If critical business constraints change during planning, the skill clears the current plan and initiates a re-plan.
- Plan Infeasibility: If no options are feasible, the skill generates an `EmptyPlan` notification, indicating human intervention is urgently required for recovery.

## Interactions
- Upstream: S2 TaskGraph (provides the tasks) and S4 RoleDispatch/S5 CollabExec (provide the task results).
- Downstream: S5 CollabExec (executes the chosen recovery plan) and S8 OrchestrationHub (final approval authority).
- Human/External: If an action is `destructive`, the plan is sent directly to the S8 OrchestrationHub for human verification via the OpsSwarm approval pipeline.
- Security: Cross-references remediation actions against `ADR-010_SECURITY_WORKFLOW_AND_POLICY.md` to ensure that no planned action violates security guardrails.

## Examples
Example Input (Diagnostic Results: Service=OrderingAPI, Symptoms=[High CPU])
Output:
RecoveryPlan(
  options=[
    RemediationOption(description="Clear API Cache", risk="safe_write", evidence="Found 90% cache hit miss rate"),
    RemediationOption(description="Scale OrderingAPI Pods", risk="risky_write", evidence="High CPU utilization on 3/4 pods"),
    RemediationOption(description="DB Migration Revert", risk="destructive", evidence="No direct link found yet")
  ],
  UnknownConstraintsInfo=["Maximum pod scaling limit reached?"]
)

Reference: `tests/unit/skill_s3/test_recovery_plan.py` for all risk classification logic tests.
