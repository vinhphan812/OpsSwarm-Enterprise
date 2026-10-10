import { defaultClient } from "@/core/api/client";
import { parseSimulation } from "@/core/api/validate";
import { isNewerVersion } from "@/core/api/version";
import { TWIN_POLL_MAX_MS, TWIN_POLL_MS } from "@/constants/twin.constant";
import { SIMULATION_STATUS } from "@/enums/simulation.enum";
import type { RetailTwinClient } from "@/types/api.type";
import type { Simulation } from "@/types/simulation.type";

/** Read-only feed of the open Simulation Twin run. The web app never writes through it. */
export interface SimulationSource {
  /**
   * Calls `onSimulation` with the open simulation, or null once none is open, and
   * `onError` when a read fails. Returns the unsubscribe function.
   */
  subscribe(onSimulation: (simulation: Simulation | null) => void, onError?: (error: unknown) => void): () => void;
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
    subscribe: (onSimulation, onError) => {
      let active = true;
      let delay = intervalMs;
      let current: Simulation | null = null;
      let delivered = false;
      let timer: ReturnType<typeof setTimeout>;

      const read = async (): Promise<Simulation | null> => {
        const { simulations } = await client.simulations();
        const open = simulations.find((summary) => OPEN.includes(summary.status));
        return open ? parseSimulation(await client.simulation(open.simulation_id)) : null;
      };

      const poll = async () => {
        if (!tabHidden()) {
          try {
            const next = await read();
            if (!active) return;
            delay = intervalMs;
            if (next === null ? current !== null || !delivered : isNewerSimulation(next, current)) {
              current = next;
              delivered = true;
              onSimulation(next);
            }
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
