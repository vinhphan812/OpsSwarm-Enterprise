import { beforeEach, describe, expect, it } from "vitest";
import { createMemoryTwin, patchProduct, type MemoryTwin } from "@/core/api/sources/memorySource";
import { commitSimulation, discardSimulation, openSimulation } from "@/core/twin/memorySimulation";
import { ACTION_TYPE } from "@/enums/simulation.enum";
import { demoStoreState } from "@/fixtures/demo/store";
import { useTwinStore } from "@/state/twin.store";
import type { StoreResponse } from "@/types/twin.type";

const sku = (state: StoreResponse, id: string) => state.products.find((product) => product.sku === id)!;

describe("simulations on the memory twin", () => {
  let twin: MemoryTwin;
  let pushed: StoreResponse[];

  beforeEach(() => {
    useTwinStore.setState(useTwinStore.getInitialState(), true);
    twin = createMemoryTwin(demoStoreState());
    pushed = [];
    twin.source.subscribe((state) => pushed.push(state));
  });

  it("opens a simulation without touching Live", () => {
    const before = twin.current();
    openSimulation(twin);

    const simulation = useTwinStore.getState().simulation!;
    expect(simulation.base_context_version).toBe(before.context_version);
    expect(sku(simulation.state, "P003")).toMatchObject({ shelf_quantity: 12, backroom_quantity: 6 });
    expect(twin.current()).toEqual(before);
    expect(pushed).toEqual([]);
  });

  it("simulates the actions it is given", () => {
    openSimulation(twin, [{ type: ACTION_TYPE.ChangeFacings, sku: "P001", facings: 5 }]);
    const simulation = useTwinStore.getState().simulation!;
    expect(simulation.actions).toHaveLength(1);
    expect(sku(simulation.state, "P001").facings).toBe(5);
    expect(sku(simulation.state, "P003").shelf_quantity).toBe(0);
  });

  it("commits through the live feed and closes the simulation", () => {
    openSimulation(twin);
    const version = commitSimulation(twin);

    expect(useTwinStore.getState().simulation).toBeNull();
    expect(pushed).toHaveLength(1);
    expect(pushed[0].context_version).toBe(version);
    expect(version).not.toBe(demoStoreState().context_version);
    expect(sku(pushed[0], "P007")).toMatchObject({ shelf_id: "B02", slot_id: "B02-S22" });
  });

  it("refuses to commit once Live has moved on (REFRESH_REQUIRED), and leaves Live alone", () => {
    openSimulation(twin);
    twin.update((state) => patchProduct(state, "P002", { shelf_quantity: 9 }));
    const live = twin.current();

    expect(() => commitSimulation(twin)).toThrow("REFRESH_REQUIRED");
    expect(twin.current()).toEqual(live);
    expect(useTwinStore.getState().simulation).not.toBeNull();
  });

  it("discards a simulation without touching Live", () => {
    const before = twin.current();
    openSimulation(twin);
    discardSimulation();
    expect(useTwinStore.getState().simulation).toBeNull();
    expect(twin.current()).toEqual(before);
    expect(() => commitSimulation(twin)).toThrow("No simulation is open.");
  });
});
