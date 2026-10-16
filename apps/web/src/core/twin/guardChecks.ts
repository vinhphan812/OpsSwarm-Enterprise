import { GUARD_GATES } from "@/enums/simulation.enum";
import type { GuardResult } from "@/types/simulation.type";

export const GATE_STATE = {
  Passed: "passed",
  Failed: "failed",
  NotRun: "notRun",
} as const;
export type GateState = (typeof GATE_STATE)[keyof typeof GATE_STATE];

export type GateRow = { gate: string; state: GateState; detail: string };

/**
 * The guard's gates as rows: each check it sent, in the order it ran them, then the gates it
 * never reached after the one that failed. A guard that sent no checks gives no rows, so
 * nothing is listed that the guard did not report.
 */
export function gateRows(guard: GuardResult): GateRow[] {
  const rows: GateRow[] = guard.checks.map((check) => ({
    gate: check.gate,
    state: check.passed ? GATE_STATE.Passed : GATE_STATE.Failed,
    detail: check.detail,
  }));
  const failedAt = guard.failed_gate ? GUARD_GATES.indexOf(guard.failed_gate) : -1;
  if (!rows.length || failedAt < 0) return rows;
  const reported = new Set(rows.map((row) => row.gate));
  for (const gate of GUARD_GATES.slice(failedAt + 1)) {
    if (!reported.has(gate)) rows.push({ gate, state: GATE_STATE.NotRun, detail: "" });
  }
  return rows;
}
