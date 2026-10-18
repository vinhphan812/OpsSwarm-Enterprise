import type { MemoryTwin } from "@/core/api/sources/memorySource";
import { commitSimulation } from "@/core/twin/memorySimulation";
import { resolveAnomalies } from "@/core/twin/simulateAnomaly";
import { DEMO_AGENT_STEP_MS, DEMO_RUN_ID, replayDemoAgentRun } from "@/fixtures/demo/agentRun";
import { demoAnomalies } from "@/fixtures/demo/anomalies";
import { demoCandidates } from "@/fixtures/demo/candidates";
import { demoSimulation } from "@/fixtures/demo/simulation";
import { demoStoreState } from "@/fixtures/demo/store";
import { useAnomalyStore } from "@/state/anomaly.store";
import { useRunStore } from "@/state/run.store";
import { useTwinStore } from "@/state/twin.store";
import { DEMO_RUN_SOURCE, type DemoRunner } from "./demoRunner";

/**
 * The Run AI Demo button under `?twin=demo` (development builds, or the hosted demo):
 * fixtures/demo stand in for the flagship controller (#41) and the agent, never a real run,
 * and it never calls apps/api: every write goes to the memory twin. Its source is `replay`.
 * Reset puts the demo store, its anomalies and its open simulation back; start replays the
 * demo agent run, one stage every `stepMs`. At ACT the memory twin commits the simulation,
 * as the guarded executor would, so Live changes; at VERIFY the anomaly on the product the
 * run acted on closes, as the verifier would close it, and the run ends.
 */
export function createFixtureDemoRunner(twin: MemoryTwin, stepMs = DEMO_AGENT_STEP_MS): DemoRunner {
  return {
    source: DEMO_RUN_SOURCE.Replay,
    async start() {
      const state = twin.update(() => demoStoreState());
      useAnomalyStore.getState().setAll(demoAnomalies(state));
      useTwinStore.getState().setSimulation(demoSimulation(state));
      useTwinStore.getState().setCandidates(demoCandidates(state));
      useTwinStore.getState().selectCandidate(null);

      let unsubscribe = () => {};
      let actedOn: string | undefined;
      const done = new Promise<void>((resolve, reject) => {
        unsubscribe = useRunStore.subscribe((run, before) => {
          const entry = run.activity.length > before.activity.length ? run.activity[run.activity.length - 1] : null;
          if (entry?.correlation_id !== DEMO_RUN_ID) return;
          if (entry.stage === "ACT") {
            actedOn = entry.sku;
            try {
              commitSimulation(twin);
            } catch (error) {
              unsubscribe();
              reject(error);
            }
          }
          if (entry.stage === "VERIFY") {
            if (actedOn) resolveAnomalies(actedOn);
            unsubscribe();
            resolve();
          }
        });
      });
      const stopReplay = replayDemoAgentRun(stepMs);
      return {
        correlationId: DEMO_RUN_ID,
        done,
        stop: () => {
          stopReplay();
          unsubscribe();
        },
      };
    },
  };
}
