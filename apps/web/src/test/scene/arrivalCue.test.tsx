// @vitest-environment jsdom
import ReactThreeTestRenderer from "@react-three/test-renderer";
import { cleanup } from "@testing-library/react";
import { Matrix4, Vector3, type InstancedMesh, type Object3D } from "three";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { ARRIVAL_GROW_MS, ARRIVAL_SPREAD_MS } from "@/constants/twin.constant";
import { diffStates } from "@/core/twin/stateDiff";
import { TWIN_STATUS } from "@/enums/twin.enum";
import { VIEW_MODE } from "@/enums/ui.enum";
import { demoSimulation } from "@/fixtures/demo/simulation";
import { demoStoreState } from "@/fixtures/demo/store";
import { toSceneStore } from "@/scene/layout";
import { TwinStoreContents } from "@/scene/StoreScene";
import { buildStock, drawnCounts } from "@/scene/entities/stock/Stock";
import { arrivalCueOf, arrivalDone, arrivalProgress, gainedSkus, growMatrix } from "@/scene/entities/stock/arrivalCue";
import { useTwinStore } from "@/state/twin.store";
import { useUiStore } from "@/state/ui.store";

const motion = vi.hoisted(() => ({ reduced: false }));
vi.mock("@/core/utils/motion", () => ({ prefersReducedMotion: () => motion.reduced }));
vi.mock("@/hooks/checkout.hook", () => ({ useCheckoutSummary: () => null, useCheckoutTransactions: () => [] }));

const live = demoStoreState();
const simulation = demoSimulation(live);
const before = drawnCounts(buildStock(toSceneStore(live).store));
const after = drawnCounts(buildStock(toSceneStore(simulation.state).store));

describe("arrivalCueOf", () => {
  const change = { diff: diffStates(live, simulation.state), at: 1000, before: live };

  it("takes the restocked P003 and the re-faced P004, never a moved product", () => {
    expect([...gainedSkus(change)].sort()).toEqual(["P003", "P004"]);
    expect(gainedSkus(null).size).toBe(0);
  });

  it("grows in only the items each product draws past what it drew before", () => {
    const cue = arrivalCueOf(change, before, after)!;
    expect(cue.at).toBe(1000);
    // P003 was empty, so every item it draws now grows in.
    expect(cue.from.get("P003")).toBe(0);
    expect(cue.added.get("P003")).toBe(after.get("P003"));
    for (const sku of cue.from.keys()) {
      expect(cue.from.get(sku)! + cue.added.get(sku)!).toBe(after.get(sku));
    }
  });

  it("is null when nothing draws more items", () => {
    expect(arrivalCueOf(change, after, after)).toBeNull();
    expect(arrivalCueOf(null, before, after)).toBeNull();
  });

  it("starts the items one after another and finishes them all in time", () => {
    expect(arrivalProgress(1000, 1000, 0, 3)).toBe(0);
    expect(arrivalProgress(1000, 1000 + ARRIVAL_GROW_MS, 0, 3)).toBe(1);
    expect(arrivalProgress(1000, 1000 + ARRIVAL_GROW_MS, 2, 3)).toBe(0);
    expect(arrivalProgress(1000, 1000 + ARRIVAL_SPREAD_MS + ARRIVAL_GROW_MS, 2, 3)).toBe(1);
    expect(arrivalDone(1000, 1000 + ARRIVAL_SPREAD_MS + ARRIVAL_GROW_MS - 1)).toBe(false);
    expect(arrivalDone(1000, 1000 + ARRIVAL_SPREAD_MS + ARRIVAL_GROW_MS)).toBe(true);
  });

  it("grows an item from the middle of its bottom face, past full size, and ends at the state", () => {
    const at = new Matrix4().makeTranslation(1, 2, 3);
    const bottom = (matrix: Matrix4) => new Vector3(0, -0.5, 0).applyMatrix4(matrix);
    const top = (matrix: Matrix4) => new Vector3(0, 0.5, 0).applyMatrix4(matrix);
    expect(bottom(growMatrix(at, 0.3)).distanceTo(bottom(at))).toBeCloseTo(0);
    expect(top(growMatrix(at, 0)).y).toBeCloseTo(1.5, 2);
    expect(top(growMatrix(at, 0.7)).y).toBeGreaterThan(2.5);
    expect(growMatrix(at, 1).equals(at)).toBe(true);
  });
});

describe("arrival cue in the scene", () => {
  let now = 0;
  let unmount: (() => Promise<void>) | null = null;

  beforeEach(() => {
    now = 1_000_000;
    vi.spyOn(Date, "now").mockImplementation(() => now);
    motion.reduced = false;
    useTwinStore.setState(useTwinStore.getInitialState(), true);
    useUiStore.setState(useUiStore.getInitialState(), true);
    useTwinStore.getState().setLive(live);
    useTwinStore.getState().setStatus(TWIN_STATUS.Ready);
    useTwinStore.getState().setSimulation(simulation);
    now += 60_000;
  });
  afterEach(async () => {
    await unmount?.();
    unmount = null;
    cleanup();
    vi.restoreAllMocks();
  });

  async function renderScene() {
    const renderer = await ReactThreeTestRenderer.create(<TwinStoreContents interactive={false} />);
    unmount = () => renderer.unmount();
    /** How tall each P003 item is drawn now, against where the state puts it. */
    const p003Scales = () => {
      const scales: number[] = [];
      renderer.scene.instance.traverse((object: Object3D) => {
        if (!object.name && object.userData.stockItems) {
          const items = object.userData.stockItems as { productId: string; matrix: Matrix4 }[];
          items.forEach((item, index) => {
            if (item.productId !== "P003") return;
            const drawn = new Matrix4();
            (object as InstancedMesh).getMatrixAt(index, drawn);
            scales.push(new Vector3().setFromMatrixScale(drawn).y / new Vector3().setFromMatrixScale(item.matrix).y);
          });
        }
      });
      return scales;
    };
    const run = (change: () => void) => ReactThreeTestRenderer.act(async () => change());
    const frameAt = async (time: number) => {
      now = time;
      await renderer.advanceFrames(1, 0.016);
    };
    return { p003Scales, run, frameAt };
  }

  it("grows the restocked P003 in on the Simulation view and ends at the state", async () => {
    const scene = await renderScene();
    expect(scene.p003Scales()).toHaveLength(0);
    await scene.run(() => useUiStore.getState().setViewMode(VIEW_MODE.Simulation));
    const start = now;
    await scene.frameAt(start + ARRIVAL_GROW_MS / 2);
    const growing = scene.p003Scales();
    expect(growing).toHaveLength(after.get("P003")!);
    expect(growing[0]).toBeGreaterThan(0.1);
    expect(growing.at(-1)!).toBeLessThan(0.01);
    await scene.frameAt(start + ARRIVAL_SPREAD_MS + ARRIVAL_GROW_MS);
    for (const scale of scene.p003Scales()) expect(scale).toBeCloseTo(1);
  });

  it("draws P003 at full size at once with reduced motion", async () => {
    motion.reduced = true;
    const scene = await renderScene();
    await scene.run(() => useUiStore.getState().setViewMode(VIEW_MODE.Simulation));
    await scene.frameAt(now + 1);
    const scales = scene.p003Scales();
    expect(scales.length).toBeGreaterThan(0);
    for (const scale of scales) expect(scale).toBeCloseTo(1);
  });
});
