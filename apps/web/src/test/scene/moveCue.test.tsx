// @vitest-environment jsdom
import ReactThreeTestRenderer from "@react-three/test-renderer";
import { act, cleanup, render, screen } from "@testing-library/react";
import { Matrix4, Vector3, type InstancedMesh, type Object3D } from "three";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { ProductInspector } from "@/components/twin/ProductInspector";
import { MOVE_ARC_HEIGHT } from "@/constants/scene.constant";
import { MOVE_MARK_IN_MS, MOVE_MARK_OUT_MS, MOVE_TWEEN_MS } from "@/constants/twin.constant";
import { diffStates } from "@/core/twin/stateDiff";
import { TWIN_STATUS } from "@/enums/twin.enum";
import { VIEW_MODE } from "@/enums/ui.enum";
import { demoSimulation } from "@/fixtures/demo/simulation";
import { demoStoreState } from "@/fixtures/demo/store";
import { toSceneStore } from "@/scene/layout";
import { TwinStoreContents } from "@/scene/StoreScene";
import { buildStock } from "@/scene/entities/stock/Stock";
import { ghostOutlines, markLevels, marksShown, moveCueOf, moveProgress, tweenMatrix } from "@/scene/entities/stock/moveCue";
import { useTwinStore } from "@/state/twin.store";
import { useUiStore } from "@/state/ui.store";

const motion = vi.hoisted(() => ({ reduced: false }));
vi.mock("@/core/utils/motion", () => ({ prefersReducedMotion: () => motion.reduced }));
vi.mock("@/hooks/checkout.hook", () => ({ useCheckoutSummary: () => null, useCheckoutTransactions: () => [] }));

const live = demoStoreState();
const simulation = demoSimulation(live);
const simulated = toSceneStore(simulation.state).store;

/** The demo moves P005, P007 and P008; each lights its source and destination slot. */
const MOVED = ["P005", "P007", "P008"];
const MOVED_SLOTS = 2 * MOVED.length;

/** Where the simulation puts each P007 item. */
const p007AtState = Object.values(buildStock(simulated))
  .flat()
  .filter((item) => item.productId === "P007")
  .map((item) => new Vector3().setFromMatrixPosition(item.matrix));

describe("moveCueOf", () => {
  const change = { diff: diffStates(live, simulation.state), at: 1000, before: live };

  it("offsets P007 from B02-S22 back to B02-S20, lights both slots and keeps a ghost of the source", () => {
    const cue = moveCueOf(simulated, change)!;
    expect([...cue.offsets.keys()]).toEqual(MOVED);
    const offset = cue.offsets.get("P007")!;
    expect(offset.length()).toBeGreaterThan(0.1);
    expect(cue.fromSlots).toHaveLength(MOVED.length);
    expect(cue.toSlots).toHaveLength(MOVED.length);
    expect(cue.ghost.products).toContainEqual(expect.objectContaining({ productId: "P007", slotId: "B02-S20" }));
    expect(cue.ghost.products.map((product) => product.productId).sort()).toEqual(MOVED);
  });

  it("shows nothing when the scene does not have the product where the move put it", () => {
    expect(moveCueOf(toSceneStore(live).store, change)).toBeNull();
    expect(moveCueOf(simulated, null)).toBeNull();
  });

  it("outlines each moved product once, around every item it had at its source", () => {
    const cue = moveCueOf(simulated, change)!;
    const items = Object.values(buildStock(cue.ghost)).flat();
    const outlines = ghostOutlines(cue, items);
    expect(outlines).toHaveLength(MOVED.length);
    for (const item of items) {
      const center = new Vector3().setFromMatrixPosition(item.matrix);
      const inside = outlines.some((outline) => {
        const local = center.clone().applyMatrix4(outline.clone().invert());
        return Math.max(Math.abs(local.x), Math.abs(local.y), Math.abs(local.z)) <= 0.5 + 1e-6;
      });
      expect(inside, item.productId).toBe(true);
    }
  });

  it("shows the outline and lights while the items travel and as they fade out", () => {
    expect(marksShown(1000, 1000)).toBe(true);
    expect(marksShown(1000, 1000 + MOVE_TWEEN_MS)).toBe(true);
    expect(marksShown(1000, 1000 + MOVE_TWEEN_MS + MOVE_MARK_OUT_MS)).toBe(false);
    // Reduced motion has no fade: they go when the items would have arrived.
    expect(marksShown(1000, 1000 + MOVE_TWEEN_MS - 1, false)).toBe(true);
    expect(marksShown(1000, 1000 + MOVE_TWEEN_MS, false)).toBe(false);
  });

  it("fades the marks in, hands the light from source to destination, flashes on arrival and fades out", () => {
    expect(markLevels(1000, 1000)).toEqual({ ghost: 0, from: 0, to: 0, flash: 0 });
    const early = markLevels(1000, 1000 + MOVE_MARK_IN_MS);
    expect(early.ghost).toBe(1);
    expect(early.from).toBeGreaterThan(early.to);
    const late = markLevels(1000, 1000 + MOVE_TWEEN_MS - 1);
    expect(late.to).toBeGreaterThan(late.from);
    expect(late.flash).toBe(0);
    const landed = markLevels(1000, 1000 + MOVE_TWEEN_MS);
    expect(landed.to).toBe(1);
    expect(landed.flash).toBeGreaterThan(0);
    const fading = markLevels(1000, 1000 + MOVE_TWEEN_MS + MOVE_MARK_OUT_MS / 2);
    expect(fading.ghost).toBeCloseTo(0.5);
    expect(fading.flash).toBeLessThan(landed.flash);
    expect(markLevels(1000, 1000 + MOVE_TWEEN_MS + MOVE_MARK_OUT_MS)).toEqual({ ghost: 0, from: 0, to: 0, flash: 0 });
  });

  it("tweens from the source to exactly the state position", () => {
    const at = new Matrix4().makeTranslation(1, 2, 3);
    const offset = new Vector3(-2, 0, 0);
    expect(moveProgress(1000, 1000 - 50)).toBe(0);
    expect(moveProgress(1000, 1000 + MOVE_TWEEN_MS / 2)).toBeCloseTo(0.5);
    expect(moveProgress(1000, 1000 + MOVE_TWEEN_MS * 3)).toBe(1);
    expect(new Vector3().setFromMatrixPosition(tweenMatrix(at, offset, 0)).toArray()).toEqual([-1, 2, 3]);
    const midway = new Vector3().setFromMatrixPosition(tweenMatrix(at, offset, 0.5));
    expect(midway.x).toBeCloseTo(0);
    // The items hop: highest midway, back on the shelf at both ends.
    expect(midway.y).toBeCloseTo(2 + MOVE_ARC_HEIGHT);
    expect(tweenMatrix(at, offset, 1).equals(at)).toBe(true);
  });
});

describe("move cue in the scene", () => {
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
    const find = (prefix: string) => {
      const found: InstancedMesh[] = [];
      renderer.scene.instance.traverse((object: Object3D) => {
        if (object.name.startsWith(prefix)) found.push(object as InstancedMesh);
      });
      return found;
    };
    /** Where each P007 item is drawn now. */
    const p007 = () => {
      const drawn: Vector3[] = [];
      renderer.scene.instance.traverse((object: Object3D) => {
        const items = object.userData.stockItems as { productId: string }[] | undefined;
        items?.forEach((item, index) => {
          if (item.productId !== "P007") return;
          const matrix = new Matrix4();
          (object as InstancedMesh).getMatrixAt(index, matrix);
          drawn.push(new Vector3().setFromMatrixPosition(matrix));
        });
      });
      return drawn;
    };
    const run = (change: () => void) => ReactThreeTestRenderer.act(async () => change());
    const frameAt = async (time: number) => {
      now = time;
      await renderer.advanceFrames(1, 0.016);
    };
    /** How many slot lights are drawn, source and destination together. */
    const slotLights = () => find("stock-moved-slots-").reduce((sum, mesh) => sum + mesh.count, 0);
    /** True while the outline and slot lights are drawn. */
    const marked = () => renderer.scene.instance.getObjectByName("stock-move-marks")?.visible === true;
    return { find, p007, run, frameAt, marked, slotLights };
  }

  const atState = (drawn: Vector3[]) => drawn.every((point, index) => point.distanceTo(p007AtState[index]) < 1e-6);

  it("carries P007 to B02-S22 in the Simulation view and ends where the state puts it", async () => {
    const scene = await renderScene();
    expect(scene.find("stock-ghost-")).toHaveLength(0);

    await scene.run(() => useUiStore.getState().setViewMode(VIEW_MODE.Simulation));
    const start = now;
    expect(scene.slotLights()).toBe(MOVED_SLOTS);
    expect(scene.find("stock-ghost-outline")).toHaveLength(MOVED.length);

    await scene.frameAt(start + MOVE_TWEEN_MS / 2);
    expect(scene.p007()).toHaveLength(p007AtState.length);
    expect(atState(scene.p007())).toBe(false);
    expect(scene.marked()).toBe(true);

    // The items land where the state puts them; the outline and lights then fade out.
    await scene.frameAt(start + MOVE_TWEEN_MS);
    expect(atState(scene.p007())).toBe(true);
    expect(scene.marked()).toBe(true);
    await scene.frameAt(start + MOVE_TWEEN_MS + MOVE_MARK_OUT_MS);
    expect(scene.marked()).toBe(false);
  });

  it("puts P007 straight at its destination with reduced motion, and still marks the move", async () => {
    motion.reduced = true;
    const scene = await renderScene();
    await scene.run(() => useUiStore.getState().setViewMode(VIEW_MODE.Simulation));
    await scene.frameAt(now);
    expect(atState(scene.p007())).toBe(true);
    expect(scene.slotLights()).toBe(MOVED_SLOTS);
    expect(scene.find("stock-ghost-").length).toBeGreaterThan(0);
  });

  it("leaves Live alone while the Simulation view shows the move, and plays the move back on the way out", async () => {
    const scene = await renderScene();
    await scene.run(() => useUiStore.getState().setViewMode(VIEW_MODE.Simulation));
    now += 60_000;
    await scene.run(() => useUiStore.getState().setViewMode(VIEW_MODE.Live));
    expect(scene.slotLights()).toBe(MOVED_SLOTS);
    expect(scene.find("stock-ghost-outline")).toHaveLength(MOVED.length);
    const inLive = Object.values(buildStock(toSceneStore(live).store))
      .flat()
      .filter((item) => item.productId === "P007")
      .map((item) => new Vector3().setFromMatrixPosition(item.matrix));
    const atLive = () => scene.p007().every((point, index) => point.distanceTo(inLive[index]) < 1e-6);
    await scene.frameAt(now + MOVE_TWEEN_MS / 2);
    expect(atLive()).toBe(false);
    await scene.frameAt(now + MOVE_TWEEN_MS);
    expect(atLive()).toBe(true);
    expect(useTwinStore.getState().live).toBe(live);
    expect(useTwinStore.getState().live?.products.find((product) => product.sku === "P007")?.slot_id).toBe("B02-S20");
  });

  it("cues a move that comes in on the live feed", async () => {
    const scene = await renderScene();
    await scene.run(() => useTwinStore.getState().setLive(simulation.state));
    expect(scene.slotLights()).toBe(MOVED_SLOTS);
    await scene.frameAt(now + MOVE_TWEEN_MS);
    expect(atState(scene.p007())).toBe(true);
  });

  it("animates a rollback on the live feed back to the source slot", async () => {
    const scene = await renderScene();
    await scene.run(() => useTwinStore.getState().setLive(simulation.state));
    now += 60_000;
    await scene.run(() => useTwinStore.getState().setLive(live));
    const back = useTwinStore.getState().liveChange?.diff.moved;
    expect(back?.map((move) => move.sku)).toEqual(MOVED);
    expect(back).toContainEqual({ sku: "P007", from: { shelf_id: "B02", slot_id: "B02-S22" }, to: { shelf_id: "B02", slot_id: "B02-S20" } });
    expect(scene.slotLights()).toBe(MOVED_SLOTS);
    const original = Object.values(buildStock(toSceneStore(live).store))
      .flat()
      .filter((item) => item.productId === "P007")
      .map((item) => new Vector3().setFromMatrixPosition(item.matrix));
    const atOriginal = () => scene.p007().every((point, index) => point.distanceTo(original[index]) < 1e-6);
    await scene.frameAt(now + MOVE_TWEEN_MS / 2);
    expect(atOriginal()).toBe(false);
    await scene.frameAt(now + MOVE_TWEEN_MS);
    expect(atOriginal()).toBe(true);
  });

  it("says where P007 came from on its card while the move is recent", () => {
    useUiStore.getState().setViewMode(VIEW_MODE.Simulation);
    render(<ProductInspector productId="P007" />);
    expect(screen.getByText("Moved from B02-S20")).toBeTruthy();
    cleanup();
    render(<ProductInspector productId="P004" />);
    expect(screen.queryByText(/Moved from/)).toBeNull();
    act(() => useUiStore.getState().setViewMode(VIEW_MODE.Live));
  });
});
