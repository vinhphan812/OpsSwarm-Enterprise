import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { createSimulationSource, isNewerSimulation } from "@/core/api/sources/simulationSource";
import { parseSimulation } from "@/core/api/validate";
import { SIMULATION_STATUS } from "@/enums/simulation.enum";
import { simulationOf, DEMO_ACTIONS } from "@/fixtures/demo/simulation";
import { sampleStoreState } from "@/test/sampleState";
import type { RetailTwinClient } from "@/types/api.type";
import type { Simulation, SimulationsResponse } from "@/types/simulation.type";

const ACTIONS = [{ type: "change_facings", sku: "P001", facings: 5 }] as typeof DEMO_ACTIONS;
const run = (id = "sim-001", change: Partial<Simulation> = {}): Simulation => ({
  ...simulationOf(sampleStoreState(), ACTIONS, id),
  ...change,
});
const listOf = (...runs: Simulation[]): SimulationsResponse => ({
  simulations: runs.map(({ simulation_id, store_id, base_context_version, status }) => ({
    simulation_id,
    store_id,
    base_context_version,
    status,
  })),
});

function fakeClient(simulations: RetailTwinClient["simulations"], simulation: RetailTwinClient["simulation"]): RetailTwinClient {
  return {
    health: vi.fn(),
    store: vi.fn(),
    inventory: vi.fn(),
    revenue: vi.fn(),
    promotions: vi.fn(),
    simulations,
    simulation,
    reviewSimulation: vi.fn(),
  };
}

describe("parseSimulation", () => {
  it("accepts a run and checks its proposed state like GET /store", () => {
    const raw = run();
    raw.state.products.push({ ...raw.state.products[0], sku: "BAD", slot_id: null } as never);
    const parsed = parseSimulation(raw);
    expect(parsed.simulation_id).toBe("sim-001");
    expect(parsed.state.products.map((product) => product.sku)).not.toContain("BAD");
  });

  it("rejects a payload that breaks the contract", () => {
    expect(() => parseSimulation(null)).toThrow("not an object");
    expect(() => parseSimulation({ ...run(), base_context_version: "" })).toThrow("missing base_context_version");
    expect(() => parseSimulation({ ...run(), status: "done" })).toThrow("invalid status");
    expect(() => parseSimulation({ ...run(), actions: [{ type: "teleport", sku: "P001" }] })).toThrow("invalid actions");
    expect(() => parseSimulation({ ...run(), store_id: "store-999" })).toThrow("invalid state.store_id");
    expect(() => parseSimulation({ ...run(), state: { products: [] } })).toThrow("missing store_id");
  });
});

describe("isNewerSimulation", () => {
  it("takes another run, another status or a newer proposal, and drops older or repeated reads", () => {
    const base = run();
    const newer = run("sim-001", { state: { ...base.state, context_version: "store-001:v99" } });
    expect(isNewerSimulation(base, null)).toBe(true);
    expect(isNewerSimulation(run("sim-002"), base)).toBe(true);
    expect(isNewerSimulation(run("sim-001", { status: SIMULATION_STATUS.Pending }), base)).toBe(true);
    expect(isNewerSimulation(newer, base)).toBe(true);
    expect(isNewerSimulation(base, newer)).toBe(false);
    expect(isNewerSimulation(run(), base)).toBe(false);
  });
});

describe("simulationSource", () => {
  beforeEach(() => vi.useFakeTimers());
  afterEach(() => vi.useRealTimers());

  it("reads the open run right away, delivers it once, and stops on unsubscribe", async () => {
    const simulations = vi.fn<RetailTwinClient["simulations"]>().mockResolvedValue(listOf(run()));
    const simulation = vi.fn<RetailTwinClient["simulation"]>().mockResolvedValue(run());
    const onSimulation = vi.fn();
    const unsubscribe = createSimulationSource(fakeClient(simulations, simulation), 1000).subscribe(onSimulation);

    await vi.advanceTimersByTimeAsync(2500);
    expect(simulation).toHaveBeenCalledWith("sim-001");
    expect(onSimulation).toHaveBeenCalledTimes(1);
    expect(onSimulation).toHaveBeenCalledWith(expect.objectContaining({ simulation_id: "sim-001" }));

    unsubscribe();
    await vi.advanceTimersByTimeAsync(5000);
    expect(simulations).toHaveBeenCalledTimes(3);
  });

  it("skips runs that are no longer open, and delivers null once the run closes", async () => {
    const committed = run("sim-000", { status: SIMULATION_STATUS.Committed });
    const simulations = vi
      .fn<RetailTwinClient["simulations"]>()
      .mockResolvedValueOnce(listOf(committed, run()))
      .mockResolvedValue(listOf(committed));
    const simulation = vi.fn<RetailTwinClient["simulation"]>().mockResolvedValue(run());
    const onSimulation = vi.fn();
    createSimulationSource(fakeClient(simulations, simulation), 1000).subscribe(onSimulation);

    await vi.advanceTimersByTimeAsync(2500);
    expect(simulation).toHaveBeenCalledTimes(1);
    expect(onSimulation.mock.calls.map(([next]) => next?.simulation_id ?? null)).toEqual(["sim-001", null]);
  });

  it("keeps the last run on a failed or unreadable read, and waits longer up to the cap", async () => {
    const simulations = vi
      .fn<RetailTwinClient["simulations"]>()
      .mockResolvedValueOnce(listOf(run()))
      .mockRejectedValueOnce(new Error("404"))
      .mockRejectedValueOnce(new Error("404"))
      .mockResolvedValue(listOf(run()));
    const simulation = vi
      .fn<RetailTwinClient["simulation"]>()
      .mockResolvedValueOnce(run())
      .mockResolvedValue({ broken: true } as never);
    const onSimulation = vi.fn();
    const onError = vi.fn();
    createSimulationSource(fakeClient(simulations, simulation), 1000, 3000).subscribe(onSimulation, onError);

    await vi.advanceTimersByTimeAsync(0); // first read
    await vi.advanceTimersByTimeAsync(1000); // fails, waits 2000
    await vi.advanceTimersByTimeAsync(2000); // fails, waits 3000 (cap)
    expect(simulations).toHaveBeenCalledTimes(3);
    await vi.advanceTimersByTimeAsync(2999);
    expect(simulations).toHaveBeenCalledTimes(3);
    await vi.advanceTimersByTimeAsync(1); // unreadable run
    expect(onError).toHaveBeenCalledTimes(3);
    expect(onSimulation).toHaveBeenCalledTimes(1);
  });
});
