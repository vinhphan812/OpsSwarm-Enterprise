import type { AssistantTurn } from "@/types/assistant.type";

/** A served reply to `msg-1` of `conv-1`, as apps/api would send it. */
export function servedTurn(extra: Record<string, unknown> = {}): Record<string, unknown> {
  return {
    conversation_id: "conv-1",
    message_id: "msg-1",
    reply_id: "reply-1",
    correlation_id: "copilot-1",
    run_id: null,
    store_id: "store-001",
    context_version: "store-001:v7",
    source: "vertex_gemini",
    model: "gemini-2.5-flash",
    status: "answered",
    outcome_code: null,
    text: "P017 is low on the shelf.",
    evidence: [
      {
        id: "inventory:P017",
        kind: "inventory",
        label: "Shelf and backroom",
        detail: "Shelf 2 · backroom 30",
        source: "firestore",
        tool: "get_inventory",
        sku: "P017",
        as_of: "store-001:v7",
        confidence: null,
      },
    ],
    tool_calls: [{ tool: "get_inventory", capability: "read", ok: true, error_code: null, sku: "P017", duration_ms: 120 }],
    proposal: null,
    created_at: "2026-10-18T10:00:00Z",
    ...extra,
  };
}

/** A served plan for P017, as apps/api would send it. */
export function servedProposal(extra: Record<string, unknown> = {}) {
  return {
    simulation_id: "sim-9",
    candidate_id: "cand-1",
    decision_id: "dec-1",
    base_context_version: "store-001:v7",
    actions: [{ type: "replenish_shelf", sku: "P017", quantity: 12 }],
    summary: "Restock P017 +12",
    kpis: [{ name: "stockout_risk", value: 0.1, unit: "share", source: "simulation-kpi-v1" }],
    baseline_kpis: [{ name: "stockout_risk", value: 0.4, unit: "share", source: "simulation-kpi-v1" }],
    evaluator_version: "simulation-kpi-v1",
    constraints: [{ label: "Restock fits the backroom", passed: true }],
    guard: null,
    ...extra,
  };
}

export const asTurn = (raw: Record<string, unknown>) => raw as unknown as AssistantTurn;
