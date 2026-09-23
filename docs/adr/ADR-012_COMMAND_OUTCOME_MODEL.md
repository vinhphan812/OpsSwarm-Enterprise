# ADR-012: Command Outcome Model

**Status:** Proposed  
**Created:** 2026-09-23  
**Related:** Issue #9, ADR-009-5

## Context

Reviewer `stringsofthemind-oss` (Issue #9) identified a critical invariant: "stable operation identity survives webhook replay, process restart, and transport retry". The current implementation tracks commands as RECEIVED/EXECUTING/EXECUTED, but this lacks sufficient granularity for external effects that might have succeeded despite process failure (the "crash window").

## Evaluation of Options

| Option | Description | Complexity | Test Gap | Risk |
| ------ | ----------- | ---------- | -------- | ---- |
| A | Keep current (RECEIVED/EXECUTING/EXECUTED) + atomic writes | Low | Medium | Medium (ambiguous outcomes remain) |
| B | Adopt Once-style (CONFIRMED/ABSENT/UNKNOWN) | Medium | Low | Low (explicit state for crash window) |
| C | Integrate Once library (https://github.com/stringsofthemind-oss/once) | High | Low | High (dependency risk) |

## Decision

**Adopt Option B: Command Outcome Model with CONFIRMED/ABSENT/UNKNOWN states.**

This provides the necessary explicit state to handle the crash window where a command might have been executed externally but not acknowledged internally.

### State Mapping
- RECEIVED → (No change)
- EXECUTING → (No change)
- EXECUTED → CONFIRMED (if verified via evidence), or UNKNOWN (if post-execution but pre-verification)
- FAILED → ABSENT (if determined failure) or FAILED

### Definition of CONFIRMED
CONFIRMED means the command's external effect has been successfully verified either via S7 observation evidence, or via explicit reconciliation.

## Implementation Plan

1. Update `opsswarm/models.py`:
   - Rename `CommandOutcome` enum to `CONFIRMED`, `ABSENT`, `UNKNOWN` (with backward compatibility mapping).
2. Update `opsswarm/orchestrator.py`:
   - Update crash handling logic to transition between these new states.
3. Update `docs/adr/ADR-009-5_COMMAND_DETERMINISM.md` to map its idempotency findings to the new outcome states.
4. Add reproduction test case (Process crash AFTER execute_recovery success but BEFORE mark_command_executed).

## Compatibility & Migration
- Rename enum values while keeping old values as synonyms for a transition period.
- Migrate existing `command_outcomes` entries on startup.

## Security Impact
- High: Correctly labeling ambiguous states prevents unintentional duplicate retries of production-altering commands.
