import ReactThreeTestRenderer from "@react-three/test-renderer";
import type { Object3D } from "three";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { sampleStoreState } from "./sampleState";
import { createMemoryTwin, patchProduct, type MemoryTwin } from "@/core/api/sources/memorySource";
import type { TwinSource } from "@/core/api/sources/TwinSource";
import { TwinStoreContents } from "@/scene/StoreScene";
import { useTwinStore } from "@/state/twin.store";
import { inspectProduct, twinIssues } from "@/core/twin/twinIssues";
import { useTwinSource } from "@/hooks/twinSource.hook";

// Toasts need the HeroUI provider and a DOM; this test only follows the data.
vi.mock("@/core/notify", () => ({
  errorMessage: String,
  notify: { error: vi.fn(), warning: vi.fn(), info: vi.fn(), success: vi.fn() },
}));

/** The page's data path without the canvas: source → twin store → scene graph. */
function LiveScene({ source }: { source: TwinSource }) {
  useTwinSource(source);
  return <TwinStoreContents interactive={false} />;
}

type Renderer = Awaited<ReturnType<typeof ReactThreeTestRenderer.create>>;

/** Opens the page on a fresh twin store, as a reload does, and waits for the first state. */
async function openPage(twin: MemoryTwin): Promise<Renderer> {
  useTwinStore.setState(useTwinStore.getInitialState(), true);
  const renderer = await ReactThreeTestRenderer.create(<LiveScene source={twin.source} />);
  await ReactThreeTestRenderer.act(async () => {
    await Promise.resolve();
  });
  expect(useTwinStore.getState().status).toBe("ready");
  return renderer;
}

function find(renderer: Renderer, name: string): Object3D | undefined {
  return renderer.scene.instance.getObjectByName(name);
}

/** Where P001 is drawn and what it carries, as the scene graph shows it. */
function p001(renderer: Renderer) {
  const product = find(renderer, "P001");
  if (!product) return undefined;
  const slot = product.parent!;
  return { slot: slot.name, shelf: slot.parent!.name, ...product.userData };
}

describe("P001 bound to the twin", () => {
  let twin: MemoryTwin;
  let renderer: Renderer | undefined;

  beforeEach(() => {
    twin = createMemoryTwin(sampleStoreState());
  });

  afterEach(async () => {
    await renderer?.unmount();
    renderer = undefined;
  });

  it("follows a twin change live, and a reload rebuilds the same state", async () => {
    renderer = await openPage(twin);
    expect(p001(renderer)).toMatchObject({
      slot: "A01-S01",
      shelf: "A01",
      facings: 3,
      shelfQuantity: 8,
      backroomQuantity: 42,
      version: 1,
    });

    // The backend moves P001, widens it, and refills the shelf.
    await ReactThreeTestRenderer.act(async () => {
      twin.update((state) =>
        patchProduct(state, "P001", { slot_id: "A01-S37", facings: 4, shelf_quantity: 12, backroom_quantity: 38 }),
      );
    });
    const moved = { slot: "A01-S37", shelf: "A01", facings: 4, shelfQuantity: 12, backroomQuantity: 38, version: 2 };
    expect(p001(renderer)).toMatchObject(moved);
    expect(find(renderer, "A01-S01")?.getObjectByName("P001")).toBeUndefined();
    expect(useTwinStore.getState().live?.context_version).toBe("store-001:v2");

    // Reload: nothing survives in the page; the state comes back from the twin.
    await renderer.unmount();
    expect(twin.listenerCount()).toBe(0);
    renderer = await openPage(twin);
    expect(p001(renderer)).toMatchObject(moved);
    expect(twin.listenerCount()).toBe(1);
  });

  it("drops P001 from the scene and reports why when its record breaks", async () => {
    renderer = await openPage(twin);
    const issues = () => twinIssues(useTwinStore.getState().live, useTwinStore.getState().issues);
    const inspect = () => inspectProduct("P001", useTwinStore.getState().live, issues());

    await ReactThreeTestRenderer.act(async () => {
      twin.update((state) => patchProduct(state, "P001", { slot_id: null }));
    });
    expect(find(renderer, "P001")).toBeUndefined();
    expect(inspect()).toEqual({ kind: "invalid", issue: { sku: "P001", code: "unassigned" } });

    await ReactThreeTestRenderer.act(async () => {
      twin.update((state) => patchProduct(state, "P001", { slot_id: "A01-S99" }));
    });
    expect(find(renderer, "P001")).toBeUndefined();
    expect(inspect()).toEqual({
      kind: "invalid",
      issue: { sku: "P001", code: "slotNotOnShelf", values: { slotId: "A01-S99", shelfId: "A01" } },
    });

    await ReactThreeTestRenderer.act(async () => {
      twin.update((state) => patchProduct(state, "P001", null));
    });
    expect(inspect()).toEqual({ kind: "missing" });
    expect(issues()).toEqual([]);
    // The rest of the store is still drawn.
    expect(find(renderer, "P002")).toBeDefined();
  });
});
