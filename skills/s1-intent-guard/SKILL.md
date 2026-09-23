---
name: s1-intent-guard
description: Normalize a GitHub Issue into a bounded incident context.
---

# S1 IntentGuard

## Purpose
The S1 IntentGuard skill is the foundational ingestion layer of the incident management lifecycle. Its primary responsibility is to transform raw, unstructured GitHub issue data into the structured, canonical IncidentContext object required by downstream automation. This skill operates as the first point of entry in the OpsSwarm pipeline. It ensures that every incident has a well-defined scope, severity, and context before any diagnostic or mitigation actions are initiated. By enforcing these constraints, S1 IntentGuard prevents downstream skills from operating on ambiguous or incomplete data, directly protecting the stability of the entire automated incident response system.

## Inputs
The skill accepts a structured GitHub issue dictionary (or the raw JSON representation) as input.
- `title` (string, required): Must contain the `[Incident]` prefix.
- `body` (string, required): Contains mandatory markers for `### Service`, `### Environment`, `### Symptoms`, and `### Customer impact`.
- `labels` (list of strings, optional): Used to infer severity (`sev:1` through `sev:4`).
- `user` (string, optional): The GitHub username of the actor who opened the issue.
This data is typically sourced directly from the GitHub webhook event payload or a pull/get_issue call before being sanitized and passed to this skill for parsing.

## Outputs
The skill produces a hardened IncidentContext object, which is the standard message type for the remainder of the S1-S8 pipeline.
- `service` (string): The target system affected based on the parsed body.
- `environment` (string): The deployment context (e.g., prod, staging).
- `severity` (enum: sev1, sev2, sev3, sev4): The canonical severity level derived from labels.
- `symptoms` (list of strings): A processed, structured list of all symptoms extracted from the issue description.
- `customer_impact` (string): A captured description of the user experience impact.
- `actor` (string): The originating GitHub username, validated against authorized incident reporters.
This object is then passed to the S2 TaskGraph skill, which consumes it to formulate the initial diagnostic plan.

## Key Rules & Constraints
1. Title validation: The title MUST start with the exact string `[Incident]`. Issues missing this are rejected to prevent false positives.
2. Mandatory section markers: The body must contain the exact markdown headers `### Service`, `### Symptoms`, `### Customer impact`, and `### Environment`.
3. Severity parsing: If multiple `sev:...` labels are present, the last one applied in the label set takes precedence (deterministic order).
4. Defaulting: If the `sev:*` label is completely missing, the skill defaults to `sev:4` (lowest severity) and flags the context for a human review.
5. Multiline symptom parsing: If `### Symptoms` contains a list, each line must be stripped, validated, and appended to the final symptoms list.
6. Actor extraction: The actor field is extracted from the GitHub webhook `sender` or `user` field and MUST be cross-referenced against the internal `OpsSwarm-Enterprise` allowed user list.
7. Authorization: The skill will not proceed if the originating user is not in the authorized contributor database.

## Edge Cases
- Missing mandatory fields: If a required section is missing, the skill pauses and raises a specific error to the designated human gate via the GitHub issue comment system.
- Malformed severity: If a label exists like `severity:1` (incorrect format) instead of `sev:1`, it is ignored, and the default `sev:4` is assigned.
- Invalid actor: If the issue author is unrecognized, the skill rejects the incident context to prevent unauthorized triggers.
- Empty body sections: If a section exists but is empty, the incident is flagged as `INCOMPLETE_INCIDENT_CONTEXT`, triggering a prompt for the user to provide more details.
- Policy Denial: When the incident falls outside the predefined service list in the configuration file, the skill terminates and requests the user to submit it as a general support issue.

## Interactions
- Upstream: GitHub Webhook Parser (provides raw event data).
- Downstream: S2 TaskGraph (consumes the IncidentContext to populate the task map).
- Human/External: GitHub comments are used by this skill to request more information from users who open incomplete issues (e.g., "Missing Environment marker").
- Security: The skill interacts with the internal repository policy engine to verify that the reporter has sufficient permissions to label or manage issues in the target repository.

## Examples
Example Input (GitHub Issue):
Title: [Incident] Database latency issues
Body:
### Service
OrderingAPI
### Environment
prod
### Symptoms
- 5s latency seen in traces
- High CPU on DB cluster
### Customer impact
Checkout failing for 10% users

Output:
IncidentContext(service="OrderingAPI", environment="prod", severity="sev:4", severity_defaulted=True, symptoms=["5s latency seen in traces", "High CPU on DB cluster"], customer_impact="Checkout failing for 10% users", actor="dev_user_1")

Reference: `tests/unit/skill_s1/test_parse_issue.py` for comprehensive test cases, including edge case scenarios.
