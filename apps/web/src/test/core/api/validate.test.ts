import { describe, expect, it } from "vitest";
import { sampleStoreState } from "@/test/sampleState";
import { patchProduct } from "@/core/api/sources/memorySource";
import { InvalidTwinStateError, parseCandidate, parseReviewResult, parseStoreState } from "@/core/api/validate";

const issueFor = (patch: Parameters<typeof patchProduct>[2]) => {
  const { state, issues } = parseStoreState(patchProduct(sampleStoreState(), "P001", patch));
  expect(state.products.some((p) => p.sku === "P001")).toBe(false);
  return issues.find((issue) => issue.sku === "P001");
};

describe("parseStoreState", () => {
  it("accepts the sample store as it is", () => {
    const { state, issues } = parseStoreState(sampleStoreState());
    expect(issues).toEqual([]);
    expect(state).toEqual(sampleStoreState());
  });

  it("rejects a payload that is not a store state", () => {
    expect(() => parseStoreState(null)).toThrow(InvalidTwinStateError);
    expect(() => parseStoreState({ ...sampleStoreState(), version: "" })).toThrow(/version/);
    expect(() => parseStoreState({ ...sampleStoreState(), context_version: undefined })).toThrow(/context_version/);
    expect(() => parseStoreState({ ...sampleStoreState(), products: {} })).toThrow(/products/);
  });

  it("leaves out a broken product, keeps the rest, and says why", () => {
    expect(issueFor({ slot_id: null })).toEqual({ sku: "P001", code: "unassigned" });
    expect(issueFor({ shelf_id: undefined })).toEqual({ sku: "P001", code: "unassigned" });
    expect(issueFor({ store_id: "store-002" })).toMatchObject({
      code: "wrongStore",
      values: { storeId: '"store-002"', expected: "store-001" },
    });
    expect(issueFor({ facings: -1 })).toMatchObject({ code: "invalidCount", values: { field: "facings", value: "-1" } });
    expect(issueFor({ facings: 2.5 })).toMatchObject({ code: "invalidCount", values: { field: "facings" } });
    expect(issueFor({ shelf_quantity: "8" })).toMatchObject({ code: "invalidCount", values: { field: "shelf_quantity" } });
    expect(issueFor({ backroom_quantity: -3 })).toMatchObject({
      code: "invalidCount",
      values: { field: "backroom_quantity" },
    });

    const { state } = parseStoreState(patchProduct(sampleStoreState(), "P001", { facings: -1 }));
    expect(state.products).toHaveLength(sampleStoreState().products.length - 1);
  });

  it("keeps the first of two products with the same id", () => {
    const base = sampleStoreState();
    const { state, issues } = parseStoreState({ ...base, products: [...base.products, base.products[0]] });
    expect(state.products).toHaveLength(base.products.length);
    expect(issues).toEqual([{ sku: "P001", code: "duplicateSku" }]);
  });

  it("reports a product without a sku by its position", () => {
    const base = sampleStoreState();
    const { issues } = parseStoreState({ ...base, products: [{ ...base.products[0], sku: "" }] });
    expect(issues).toEqual([{ sku: "#0", code: "missingSku" }]);
  });
});

describe("parseReviewResult", () => {
  const approved = {
    simulation_id: "sim-1",
    decision: "approve",
    status: "committed",
    verdict: "ALLOW",
    reason_code: null,
    live_context_version: "store-001:v2",
  };
  const guard = {
    verdict: "REFRESH_REQUIRED",
    reason_code: "VERSION_STALE",
    context_version: "store-001:v1",
    context_hash: "abc",
    expiry: "2026-10-15T10:00:00Z",
    policy_result: {
      failed_gate: "freshness",
      checks: [
        { gate: "integrity", passed: true, detail: "" },
        { gate: "freshness", passed: false, detail: "P002 is at v3." },
      ],
      store_id: "store-001",
    },
  };

  it("accepts an approval and a rejection, filling in missing optional fields", () => {
    expect(parseReviewResult(approved)).toEqual({ ...approved, detail_code: null, guard: null });
    expect(parseReviewResult({ simulation_id: "sim-1", decision: "reject", status: "rejected" })).toEqual({
      simulation_id: "sim-1",
      decision: "reject",
      status: "rejected",
      verdict: null,
      reason_code: null,
      live_context_version: null,
      detail_code: null,
      guard: null,
    });
  });

  it("reads apps/api's answer: approved/rejected, upper-case reasons, and the guard's checks", () => {
    const served = {
      simulation_id: "sim-1",
      decision: "approved",
      status: "evaluated",
      verdict: "REFRESH_REQUIRED",
      reason_code: "VERSION_STALE",
      live_context_version: "store-001:v3",
      detail_code: "VERSION_STALE",
      guard,
    };
    expect(parseReviewResult(served)).toEqual({
      ...served,
      decision: "approve",
      guard: {
        verdict: "REFRESH_REQUIRED",
        reason_code: "VERSION_STALE",
        context_version: "store-001:v1",
        failed_gate: "freshness",
        checks: [
          { gate: "integrity", passed: true, detail: "" },
          { gate: "freshness", passed: false, detail: "P002 is at v3." },
        ],
      },
    });
    // A refusal before the guard runs leaves the run pending and sends no guard.
    expect(
      parseReviewResult({ ...served, status: "pending", reason_code: "VERSION_MISMATCH", detail_code: null, guard: null }),
    ).toMatchObject({ status: "pending", guard: null });
  });

  it("rejects a malformed guard answer", () => {
    const served = { ...approved, status: "evaluated", verdict: "REFRESH_REQUIRED" };
    expect(() => parseReviewResult({ ...served, guard: "ok" })).toThrow(/guard/);
    expect(() => parseReviewResult({ ...served, guard: { ...guard, verdict: "MAYBE" } })).toThrow(/guard/);
    expect(() =>
      parseReviewResult({ ...served, guard: { ...guard, policy_result: { checks: [{ gate: "freshness" }] } } }),
    ).toThrow(/guard/);
    expect(() => parseReviewResult({ ...served, guard: { ...guard, policy_result: { checks: "all" } } })).toThrow(/guard/);
  });

  it("rejects an approval without a guard verdict, or an unknown verdict, decision or status", () => {
    expect(() => parseReviewResult({ ...approved, verdict: null })).toThrow(InvalidTwinStateError);
    expect(() => parseReviewResult({ ...approved, verdict: "MAYBE" })).toThrow(InvalidTwinStateError);
    expect(() => parseReviewResult({ ...approved, decision: "commit" })).toThrow(InvalidTwinStateError);
    expect(() => parseReviewResult({ ...approved, status: "done" })).toThrow(InvalidTwinStateError);
    expect(() => parseReviewResult({ ...approved, simulation_id: "" })).toThrow(InvalidTwinStateError);
    expect(() => parseReviewResult("ok")).toThrow(InvalidTwinStateError);
  });

  it("drops a verdict and a guard on a rejection, which never reaches the guard", () => {
    const rejected = { simulation_id: "sim-1", decision: "rejected", status: "rejected", verdict: "ALLOW", guard };
    expect(parseReviewResult(rejected)).toMatchObject({ decision: "reject", verdict: null, guard: null });
  });

  it("rejects a commit the guard did not allow, or an allowed approval left rejected", () => {
    expect(() => parseReviewResult({ ...approved, status: "rejected" })).toThrow(/status/);
    expect(() => parseReviewResult({ ...approved, verdict: "DENY" })).toThrow(/status/);
    expect(() => parseReviewResult({ simulation_id: "sim-1", decision: "reject", status: "committed" })).toThrow(/status/);
    expect(parseReviewResult({ ...approved, status: "evaluated", verdict: "DENY" }).status).toBe("evaluated");
    // Approving a run that was already rejected is refused, and the run stays rejected.
    expect(parseReviewResult({ ...approved, status: "rejected", verdict: "DENY" }).status).toBe("rejected");
    expect(
      parseReviewResult({ simulation_id: "sim-1", decision: "reject", status: "evaluated", reason_code: "proposal_changed" }),
    ).toMatchObject({ status: "evaluated", verdict: null, reason_code: "proposal_changed" });
  });
});

describe("parseCandidate", () => {
  const raw = (extra: Record<string, unknown> = {}) => ({
    candidate_id: "cand-b",
    simulation_id: "sim-1",
    proposed_actions: [],
    state: sampleStoreState(),
    kpis: [],
    evaluator_version: "simulation-kpi-v1",
    provenance: "test",
    ...extra,
  });

  it("reads the agent's recommendation and rationale when served (#207)", () => {
    expect(parseCandidate(raw({ recommended: true, rationale: "Less movement." }))).toMatchObject({
      recommended: true,
      rationale: "Less movement.",
    });
  });

  it("treats a missing or malformed recommendation as none", () => {
    expect(parseCandidate(raw())).toMatchObject({ recommended: false, rationale: null });
    expect(parseCandidate(raw({ recommended: "yes", rationale: "  " }))).toMatchObject({ recommended: false, rationale: null });
  });
});
