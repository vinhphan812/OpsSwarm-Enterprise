import { createApiSource } from "@/core/api/sources/apiSource";
import { createSimulationSource, type SimulationSource } from "@/core/api/sources/simulationSource";
import { fixtureSource, fixtureStoreState } from "@/core/api/sources/fixtureSource";
import { createMemoryTwin, patchProduct, type MemoryTwin } from "@/core/api/sources/memorySource";
import type { TwinSource } from "@/core/api/sources/TwinSource";
import type { ProductInventory, StoreResponse } from "@/types/twin.type";
import { FIXTURE_P001 } from "@/constants/twin.constant";
import { ANOMALY_KIND, ANOMALY_SEVERITY, type AnomalyKind, type AnomalySeverity } from "@/enums/anomaly.enum";
import { demoAnomalies } from "@/fixtures/demo/anomalies";
import { resolveAnomalies, simulateAnomaly } from "./simulateAnomaly";
import { useAnomalyStore } from "@/state/anomaly.store";
import { demoStoreState } from "@/fixtures/demo/store";
import { replayDemoAgentRun } from "@/fixtures/demo/agentRun";
import { demoCandidates } from "@/fixtures/demo/candidates";
import { demoSimulation } from "@/fixtures/demo/simulation";
import { useTwinStore } from "@/state/twin.store";
import type { SimulationAction } from "@/types/simulation.type";
import { commitSimulation, createMemoryReviewer, discardSimulation, openSimulation } from "./memorySimulation";
import { createApiReviewer, type SimulationReviewer } from "./simulationReview";

/** The editable twin behind `?twin=memory|demo`, once `pickSource` has made it. */
let memoryTwin: MemoryTwin | null = null;

/** A twin that cannot be reached: loads for a while, then fails. */
const unreachableSource: TwinSource = {
  snapshot: () =>
    new Promise((_, reject) => {
      setTimeout(() => reject(new Error("Twin API unreachable (simulated)")), 1200);
    }),
  subscribe: () => () => {},
};

/** A slow twin: the snapshot takes a few seconds, so the loading screen stays up. */
const slowSource: TwinSource = {
  snapshot: () => new Promise((resolve) => setTimeout(() => resolve(fixtureStoreState()), 4000)),
  subscribe: () => () => {},
};

/** A twin whose live feed drops a few seconds after loading; the last state stays on screen. */
const flakySource: TwinSource = {
  snapshot: () => Promise.resolve(fixtureStoreState()),
  subscribe: (_onState, onError) => {
    const timer = setTimeout(() => onError?.(new Error("Live feed closed (simulated)")), 3000);
    return () => clearTimeout(timer);
  },
};

/** Simulated twins for checking the status screens; development builds only. */
const DEV_SOURCES: Record<string, TwinSource> = {
  fixture: fixtureSource,
  offline: unreachableSource,
  slow: slowSource,
  flaky: flakySource,
};

/**
 * An editable twin for checking live updates by hand, driven from the browser console.
 * It starts from `initial`, empty shelves by default: `twin.add()` puts the API fixture's
 * P001 on A01-S01, `twin.patch("P001", { facings: 5 })` changes it, `twin.patch("P001", null)`
 * removes it, and `twin.anomalies()` lists the demo anomalies of the current state.
 * `twin.raise("P001")` raises an anomaly event on a product (a stockout unless told
 * otherwise), and `twin.resolve("P001")` closes its anomalies again.
 * `twin.simulate()` opens a simulation of the demo actions on the current state (or of the
 * actions passed in), `twin.commit()` commits it to Live as a guarded commit would, and
 * `twin.discard()` drops it. `twin.candidate("cand-b")` shows one of the open simulation's
 * candidates in the Simulation view, and `twin.candidate(null)` its own proposal again,
 * until #39's panel selects them. `twin.agentRun()` replays the demo agent run on P003 in the
 * Agent Activity timeline, which the camera follows (#28); it returns a function that stops it.
 */
function memoryTwinSource(initial: StoreResponse = fixtureStoreState()): TwinSource {
  const twin = createMemoryTwin(initial);
  memoryTwin = twin;
  Object.assign(window, {
    twin: {
      add: (product: ProductInventory = FIXTURE_P001) =>
        twin.update((state) => ({ ...state, products: [...state.products, product] })).context_version,
      patch: (sku: string, patch: Parameters<typeof patchProduct>[2]) =>
        twin.update((state) => patchProduct(state, sku, patch)).context_version,
      state: twin.current,
      anomalies: () => demoAnomalies(twin.current()),
      raise: (
        sku: string,
        kind: AnomalyKind = ANOMALY_KIND.Stockout,
        severity: AnomalySeverity = ANOMALY_SEVERITY.High,
      ) => {
        const state = twin.current();
        const product = state.products.find((candidate) => candidate.sku === sku);
        if (!product) throw new Error(`${sku} is not in the twin`);
        return simulateAnomaly(product, kind, severity, state.context_version);
      },
      resolve: resolveAnomalies,
      simulate: (...actions: SimulationAction[]) => openSimulation(twin, actions.length ? actions : undefined),
      commit: () => commitSimulation(twin),
      discard: discardSimulation,
      candidate: (id: string | null) => useTwinStore.getState().selectCandidate(id),
      agentRun: () => replayDemoAgentRun(),
    },
  });
  return twin.source;
}

/** The `?twin=` dev twin picked in the URL, or "" for apps/api. Always "" in a production build. */
function devTwinMode(): string {
  if (!import.meta.env.DEV) return "";
  const mode = new URLSearchParams(window.location.search).get("twin") ?? "";
  return mode === "memory" || mode === "demo" || mode in DEV_SOURCES ? mode : "";
}

/**
 * The open simulation from apps/api, read alongside the apps/api Live Twin. A `?twin=`
 * dev twin has none: there `twin.simulate()` and the demo fixture fill it instead.
 */
export function pickSimulationSource(): SimulationSource | null {
  return devTwinMode() ? null : createSimulationSource();
}

/**
 * Where the banner's Accept and Reject go: the review routes of apps/api, or the memory
 * twin's guarded commit under `?twin=memory|demo`. Other dev twins open no simulation, so
 * they have none. Call after `pickSource`.
 */
export function pickSimulationReviewer(): SimulationReviewer | null {
  const mode = devTwinMode();
  if (!mode) return createApiReviewer();
  return memoryTwin && (mode === "memory" || mode === "demo") ? createMemoryReviewer(memoryTwin) : null;
}

/**
 * The Live Twin from apps/api. While developing, `?twin=fixture|memory|demo|offline|slow|flaky`
 * swaps in a local twin instead. `demo` is the stocked demo store (fixtures/demo) with an
 * open demo simulation and its candidates, and turns on the other demo data too (`isDemoMode`). A production build always reads apps/api.
 */
export function pickSource(): TwinSource {
  const mode = devTwinMode();
  if (mode === "memory") return memoryTwinSource();
  if (mode === "demo") {
    useAnomalyStore.getState().setAll(demoAnomalies());
    useTwinStore.getState().setSimulation(demoSimulation());
    useTwinStore.getState().setCandidates(demoCandidates());
    return memoryTwinSource(demoStoreState());
  }
  return mode ? DEV_SOURCES[mode] : createApiSource();
}
