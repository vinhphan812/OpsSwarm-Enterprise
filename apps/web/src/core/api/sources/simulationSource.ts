import { defaultClient } from "@/core/api/client";
import { parseCandidate, parseSimulation } from "@/core/api/validate";
import { isNewerVersion } from "@/core/api/version";
import { TWIN_POLL_MAX_MS, TWIN_POLL_MS } from "@/constants/twin.constant";
import { SIMULATION_STATUS } from "@/enums/simulation.enum";
import type { RetailTwinClient } from "@/types/api.type";
import type { Candidate, Simulation } from "@/types/simulation.type";

/** Read-only feed of the open Simulation Twin run and its candidates. The web app never writes through it. */
export interface SimulationSource {
  /**
   * Calls `onUpdate` with the open simulation and its candidates, or null and [] once none is open,
   * `onError` when a read fails, and `onRead` after every good read, changed or not, so a caller can
   * tell a failure has passed. Returns the unsubscribe function.
   */
  subscribe(
    onUpdate: (simulation: Simulation | null, candidates?: Candidate[]) => void,
    onError?: (error: unknown) => void,
    onRead?: () => void,
  ): () => void;
}

const OPEN: readonly string[] = [SIMULATION_STATUS.Pending, SIMULATION_STATUS.Evaluated];

const tabHidden = () => typeof document !== "undefined" && document.hidden;

/**
 * True when `next` should replace `current`: another run, another status, or a newer
 * proposed state. An older or repeated read of the same run is dropped.
 */
export function isNewerSimulation(next: Simulation, current: Simulation | null): boolean {
  if (current === null || next.simulation_id !== current.simulation_id) return true;
  if (next.status !== current.status) return true;
  return next.state.context_version !== current.state.context_version
    && isNewerVersion(next.state.context_version, current.state.context_version);
}

/**
 * The open simulation from apps/api (`GET /simulations?status=open`, then
 * `GET /simulations/{id}`), polled like `apiSource`: a failed read doubles the wait up
 * to `maxIntervalMs` and keeps the last simulation; a good read brings the wait back.
 * Nothing is read while the tab is hidden.
 * TODO(BE): apps/api serves no simulations yet (#26), so every read fails until it does.
 */
export function createSimulationSource(
  client: RetailTwinClient = defaultClient,
  intervalMs = TWIN_POLL_MS,
  maxIntervalMs = TWIN_POLL_MAX_MS,
): SimulationSource {
  return {
    subscribe: (onUpdate, onError, onRead) => {
      let active = true;
      let delay = intervalMs;
      let currentSim: Simulation | null = null;
      let currentCandidates: Candidate[] = [];
      let delivered = false;
      let timer: ReturnType<typeof setTimeout>;

      const read = async (): Promise<{ simulation: Simulation | null; candidates: Candidate[] }> => {
        const { simulations } = await client.simulations();
        const open = simulations.find((summary) => OPEN.includes(summary.status));
        if (!open) return { simulation: null, candidates: [] };
        const sim = parseSimulation(await client.simulation(open.simulation_id));
        const candRes = await client.candidates(open.simulation_id);
        const candidates = (candRes.candidates || [])
          .map(parseCandidate)
          .filter((c) => c.simulation_id === open.simulation_id);
        return { simulation: sim, candidates };
      };

      const poll = async () => {
        if (!tabHidden()) {
          try {
            const next = await read();
            if (!active) return;
            delay = intervalMs;
            const changed =
              next.simulation === null
                ? currentSim !== null || !delivered
                : isNewerSimulation(next.simulation, currentSim) ||
                  next.candidates.length !== currentCandidates.length ||
                  JSON.stringify(next.candidates) !== JSON.stringify(currentCandidates);

            if (changed) {
              currentSim = next.simulation;
              currentCandidates = next.candidates;
              delivered = true;
              onUpdate(next.simulation, next.candidates);
            }
            onRead?.();
          } catch (error) {
            if (!active) return;
            delay = Math.min(delay * 2, maxIntervalMs);
            onError?.(error);
          }
        }
        if (active) timer = setTimeout(poll, delay);
      };

      void poll();
      return () => {
        active = false;
        clearTimeout(timer);
      };
    },
  };
}
