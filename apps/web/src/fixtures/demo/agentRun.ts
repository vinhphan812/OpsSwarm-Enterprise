import { useRunStore } from "@/state/run.store";
import type { ActivityEntry } from "@/types/agent.type";

/**
 * Demo data for `?twin=demo` (development builds only), never a real agent run: the
 * control loop on P003, which the demo store has out of stock on A01 with 18 in the
 * backroom. INVESTIGATE and ACT name the product, VERIFY only its shelf, so following
 * the agent focuses both a product and a fixture. Until #94 reads `GET /agent/events`.
 */

/** Milliseconds between two steps of the replay. */
export const DEMO_AGENT_STEP_MS = 2500;

type Step = Omit<ActivityEntry, "id" | "ts" | "correlation_id">;

const P003 = { sku: "P003", shelf_id: "A01", slot_id: "A01-S21" };

const STEPS: Step[] = [
  { stage: "OBSERVE", summary: "Polling store-001 shelf counts." },
  { stage: "DETECT", summary: "P003 is out of stock on A01-S21.", ...P003 },
  { stage: "INVESTIGATE", summary: "Checking P003: 0 on the shelf, 18 in the backroom.", ...P003 },
  { stage: "PLAN", summary: "Plan: move 12 units of P003 from the backroom to the shelf." },
  { stage: "SIMULATE", summary: "Simulated the restock: P003 back on the shelf, no other slot changes." },
  { stage: "GUARD", summary: "Guard allowed the commit: Live has not moved since the simulation." },
  { stage: "ACT", summary: "Restocking P003 +12 on A01-S21.", ...P003 },
  { stage: "VERIFY", summary: "Verifying gondola A01: P003 is back on the shelf.", shelf_id: "A01" },
];

/** The demo run's entries, stamped from `start`, one second apart. A new array per call. */
export function demoAgentRun(runId = "demo-run", start = Date.now()): ActivityEntry[] {
  return STEPS.map((step, index) => ({
    ...step,
    id: `${runId}-${index + 1}`,
    ts: new Date(start + index * 1000).toISOString(),
    correlation_id: runId,
  }));
}

/**
 * Plays the demo run into `run.store` as an agent would, one step every `stepMs`, after
 * clearing the timeline. Returns a function that stops it. `twin.agentRun()` in the console.
 */
export function replayDemoAgentRun(stepMs = DEMO_AGENT_STEP_MS): () => void {
  useRunStore.getState().reset();
  const entries = demoAgentRun(`demo-run-${Date.now()}`);
  const timers = entries.map((entry, index) =>
    setTimeout(() => useRunStore.getState().append({ ...entry, ts: new Date().toISOString() }), index * stepMs),
  );
  return () => timers.forEach(clearTimeout);
}
