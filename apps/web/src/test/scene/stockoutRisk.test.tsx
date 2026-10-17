// @vitest-environment jsdom
import ReactThreeTestRenderer from "@react-three/test-renderer";
import { Color, type InstancedMesh, type MeshBasicMaterial } from "three";
import { afterEach, beforeEach, describe, expect, it } from "vitest";
import { riskBandColor } from "@/core/utils/theme";
import { riskBandsBySku } from "@/core/twin/stockoutRisk";
import { TWIN_STATUS } from "@/enums/twin.enum";
import { OVERLAY, RISK_BAND, VIEW_MODE } from "@/enums/ui.enum";
import { demoSimulation } from "@/fixtures/demo/simulation";
import { demoStockoutRisk } from "@/fixtures/demo/stockoutRisk";
import { demoStoreState } from "@/fixtures/demo/store";
import { toSceneStore } from "@/scene/layout";
import { SlotMarksLayer, StockoutRiskLayer, riskSlotsOf } from "@/scene/entities/stock/SlotMarks";
import { useTwinStore } from "@/state/twin.store";
import { useUiStore } from "@/state/ui.store";

const live = demoStoreState();
const store = toSceneStore(live).store;
const at = (url: string) => window.history.replaceState(null, "", url);

describe("riskSlotsOf", () => {
  it("puts each product's slot in its band, P003 (A01-S21) and P010 (OC01-S01) in red", () => {
    const slots = riskSlotsOf(store, riskBandsBySku(demoStockoutRisk()));
    expect(slots[RISK_BAND.Severe].map((slot) => slot.slotId)).toEqual(expect.arrayContaining(["A01-S21", "OC01-S01"]));
    const total = Object.values(slots).reduce((sum, list) => sum + list.length, 0);
    expect(total).toBe(store.products.length);
  });

  it("leaves out a product without a band", () => {
    const slots = riskSlotsOf(store, new Map([["P003", RISK_BAND.Severe]]));
    expect(slots[RISK_BAND.Severe].map((slot) => slot.productId)).toEqual(["P003"]);
    expect(slots[RISK_BAND.Low]).toEqual([]);
  });
});

describe("stockout-risk overlay in the scene", () => {
  let unmount: (() => Promise<void>) | null = null;

  beforeEach(() => useUiStore.setState(useUiStore.getInitialState(), true));
  afterEach(async () => {
    await unmount?.();
    unmount = null;
    at("/");
  });

  async function render() {
    const renderer = await ReactThreeTestRenderer.create(<StockoutRiskLayer store={store} />);
    unmount = () => renderer.unmount();
    const mesh = (band: string) => renderer.scene.instance.getObjectByName(`stockout-risk-${band}`) as InstancedMesh | undefined;
    const toggle = () => ReactThreeTestRenderer.act(async () => useUiStore.getState().toggleOverlay(OVERLAY.StockoutRisk));
    return { mesh, toggle };
  }

  it("draws nothing while the overlay is off, so the scene is unchanged", async () => {
    at("/?twin=demo");
    const scene = await render();
    for (const band of Object.values(RISK_BAND)) expect(scene.mesh(band)).toBeUndefined();
  });

  it("tints each slot by its band on the demo once turned on, and clears it when turned off", async () => {
    at("/?twin=demo");
    const scene = await render();
    await scene.toggle();
    const red = scene.mesh(RISK_BAND.Severe)!;
    expect(red.userData.slotIds).toEqual(expect.arrayContaining(["A01-S21", "OC01-S01"]));
    expect(red.count).toBe(red.userData.slotIds.length);
    expect((red.material as MeshBasicMaterial).color.equals(new Color(riskBandColor(RISK_BAND.Severe)))).toBe(true);
    expect(scene.mesh(RISK_BAND.Low)!.count).toBeGreaterThan(0);
    await scene.toggle();
    expect(scene.mesh(RISK_BAND.Severe)).toBeUndefined();
  });

  it("colours nothing on Live, where apps/api serves no stockout risk yet", async () => {
    at("/");
    const scene = await render();
    await scene.toggle();
    for (const band of Object.values(RISK_BAND)) expect(scene.mesh(band)).toBeUndefined();
  });
});

describe("AI changes overlay", () => {
  let unmount: (() => Promise<void>) | null = null;

  beforeEach(() => {
    useTwinStore.setState(useTwinStore.getInitialState(), true);
    useUiStore.setState(useUiStore.getInitialState(), true);
    useTwinStore.getState().setLive(live);
    useTwinStore.getState().setStatus(TWIN_STATUS.Ready);
    useTwinStore.getState().setSimulation(demoSimulation(live));
    useUiStore.getState().setViewMode(VIEW_MODE.Simulation);
  });
  afterEach(async () => {
    await unmount?.();
    unmount = null;
  });

  it("outlines the proposal's slots while on, the default, and hides them when turned off", async () => {
    const simulated = toSceneStore(demoSimulation(live).state).store;
    const renderer = await ReactThreeTestRenderer.create(<SlotMarksLayer store={simulated} />);
    unmount = () => renderer.unmount();
    const outlined = () => renderer.scene.instance.children[0]?.children.filter((child) => child.name.startsWith("slot-proposed-")).length ?? 0;
    expect(outlined()).toBeGreaterThan(0);
    await ReactThreeTestRenderer.act(async () => useUiStore.getState().toggleOverlay(OVERLAY.AiChanges));
    expect(outlined()).toBe(0);
  });
});
