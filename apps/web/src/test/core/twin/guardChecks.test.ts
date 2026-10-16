import { describe, expect, it } from "vitest";
import { gateRows } from "@/core/twin/guardChecks";
import type { GuardResult } from "@/types/simulation.type";

const guard = (overrides: Partial<GuardResult>): GuardResult => ({
  verdict: "ALLOW",
  reason_code: "ALLOWED",
  context_version: "store-001:v1",
  failed_gate: null,
  checks: [],
  ...overrides,
});

describe("gateRows", () => {
  it("lists every check in the order the guard ran them", () => {
    const checks = ["integrity", "evidence", "context", "freshness", "feasibility", "policy"].map((gate) => ({
      gate,
      passed: true,
      detail: "",
    }));
    expect(gateRows(guard({ checks })).map((row) => [row.gate, row.state])).toEqual(
      checks.map((check) => [check.gate, "passed"]),
    );
  });

  it("marks the gates after the failed one as not run", () => {
    const rows = gateRows(
      guard({
        verdict: "DENY",
        failed_gate: "feasibility",
        checks: [
          { gate: "integrity", passed: true, detail: "" },
          { gate: "feasibility", passed: false, detail: "B02-S04 is occupied by P009." },
        ],
      }),
    );
    expect(rows).toEqual([
      { gate: "integrity", state: "passed", detail: "" },
      { gate: "feasibility", state: "failed", detail: "B02-S04 is occupied by P009." },
      { gate: "policy", state: "notRun", detail: "" },
    ]);
  });

  it("lists nothing when the guard sent no checks, and keeps a gate it does not know", () => {
    expect(gateRows(guard({ failed_gate: "freshness" }))).toEqual([]);
    expect(gateRows(guard({ checks: [{ gate: "budget", passed: true, detail: "" }] }))).toEqual([
      { gate: "budget", state: "passed", detail: "" },
    ]);
  });
});
