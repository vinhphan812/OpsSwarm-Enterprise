---
name: s1-intent-guard
description: Normalize a GitHub Issue into a bounded incident context.
---

# S1 IntentGuard

**Contract version:** 1.0
**ADR references:** [ADR-006](../adr/ADR-006_SKILL_FRONTMATTER_CONTRACT.md) (frontmatter), [ADR-011](../adr/ADR-011_SKILL_ARTEFACT_CONTRACT.md) (artifact structure)
**Skill number:** 1 of 8
**Pipeline position:** Ingestion / entry point

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

## Error Codes

| Code      | Name                     | Trigger                                                                      | Resolution                                             |
| --------- | ------------------------ | ---------------------------------------------------------------------------- | ------------------------------------------------------ |
| `S1-E001` | `MISSING_TITLE_PREFIX`   | `title` does not start with `[Incident]`                                     | Reporter must re-open with correct prefix              |
| `S1-E002` | `MISSING_SECTION`        | Required `### Service\|Environment\|Symptoms\|Customer impact` header absent | Request clarification via GitHub comment               |
| `S1-E003` | `INVALID_SEVERITY_LABEL` | Label format is `severity:1` instead of `sev:1`                              | Ignored; defaults to `sev:4` with flag                 |
| `S1-E004` | `UNAUTHORIZED_ACTOR`     | Reporter not in allowed user list                                            | Reject; notify opsswarm admin                          |
| `S1-E005` | `EMPTY_SECTION`          | Required section exists but has no content                                   | Flag as `INCOMPLETE_INCIDENT_CONTEXT`; request details |
| `S1-E006` | `UNKNOWN_SERVICE`        | Service name not in predefined service registry                              | Reject; ask reporter to submit as general support      |
| `S1-E007` | `PARSE_ERROR`            | Raw body cannot be parsed (malformed markdown)                               | Raise with raw payload; pause pipeline                 |
| `S1-W001` | `SEVERITY_DEFAULTED`     | No `sev:*` label found; defaulted to `sev:4`                                 | Flag for human review; pipeline continues              |

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

## Best Practices

- **Webhook hygiene:** Only forward issues labeled with `[Incident]` from the webhook handler to avoid parsing noise. Pre-filtering at the webhook layer eliminates false-positive triggers before they enter the skill.
- **Label conventions:** Use lowercase `sev:N` format only. Variations (e.g., `severity:high`, `prio:1`) are silently ignored. Document this in the issue template to prevent reporter confusion.
- **Actor allowlist maintenance:** Keep the authorized contributor list in sync with team membership (e.g., via weekly sync from the org's member list). Stale entries block legitimate incident reports.
- **Structured body template:** Provide a GitHub issue template that auto-populates the four required sections (`### Service`, `### Environment`, `### Symptoms`, `### Customer impact`). This eliminates most `S1-E002` and `S1-E005` errors at source.
- **Feedback loops:** Monitor `S1-W001` events (severity defaulted) in the evidence store to identify reporters who consistently omit severity labels; target them for process education.

## Integration Points

| Direction        | Component                   | Interface                                                                                 |
| ---------------- | --------------------------- | ----------------------------------------------------------------------------------------- |
| Upstream -> S1   | GitHub Webhook (push event) | `issue:dict` passed to `opsswarm.skill_logic.parse_issue(issue_number, issue)`            |
| S1 -> Downstream | S2 TaskGraph                | `IncidentContext` object passed to `opsswarm.skill_logic.build_tasks()`                   |
| S1 <-> Human     | GitHub Issue comments       | Error codes `S1-E002`, `S1-E005` surfaced as clarification requests                       |
| S1 -> Policy     | Allowed-user registry       | Lookup via `opsswarm.policy.is_authorized_actor(username)`                                |
| S1 -> Evidence   | Evidence store              | Append parsed context to `runtime-data/evidence/{run_id}.jsonl` (EV-YYYYMMDDHHMMSSffffff) |
