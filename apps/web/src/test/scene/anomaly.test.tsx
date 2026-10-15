// @vitest-environment jsdom
import ReactThreeTestRenderer from "@react-three/test-renderer";
import { act, cleanup, render, screen } from "@testing-library/react";
import { Color, type InstancedMesh, type MeshStandardMaterial } from "three";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { EntityInspector } from "@/components/twin/EntityInspector";
import { anomalyColor } from "@/core/utils/theme";
import { ANOMALY_SEVERITY, ANOMALY_TYPE } from "@/enums/anomaly.enum";
import { TWIN_STATUS } from "@/enums/twin.enum";
import { STOCK_SHAPE } from "@/enums/stock.enum";
import { anomalyFor } from "@/fixtures/demo/anomalies";
import { toSceneStore } from "@/scene/layout";
import { buildStock } from "@/scene/entities/stock/Stock";
import { StoreContents } from "@/scene/StoreScene";
import { useAnomalyStore } from "@/state/anomaly.store";
import { useTwinStore } from "@/state/twin.store";
import { useUiStore } from "@/state/ui.store";
import { stockedStoreState } from "@/test/stockedState";

vi.mock("@/hooks/checkout.hook", () => ({ useCheckoutSummary: () => null, useCheckoutTransactions: () => [] }));

const state = stockedStoreState();
const store = toSceneStore(state).store;
const p001 = state.products.find((product) => product.sku === "P001")!;
/** How many items the scene draws for `sku`. */
const drawnOf = (sku: string) =>
  Object.values(buildStock(toSceneStore(state).store)).flat().filter((item) => item.productId === sku).length;
const SHAPES = Object.values(STOCK_SHAPE);

/** The issue's scenario: P001 is selected, then the anomaly API reports a stockout on it. */
const stockoutOnP001 = () =>
  anomalyFor(p001, ANOMALY_TYPE.Stockout, ANOMALY_SEVERITY.High, state.context_version);

beforeEach(() => {
  useAnomalyStore.setState({ anomalies: [] });
  useTwinStore.setState({ live: state, issues: [], status: TWIN_STATUS.Ready });
  useUiStore.getState().select(null);
});

afterEach(cleanup);

describe("anomaly store", () => {
  it("replaces an anomaly raised again under the same id, and resolves it", () => {
    const { raise, resolve } = useAnomalyStore.getState();
    raise(stockoutOnP001());
    raise({ ...stockoutOnP001(), severity: ANOMALY_SEVERITY.Medium });
    expect(useAnomalyStore.getState().anomalies).toHaveLength(1);
    expect(useAnomalyStore.getState().anomalies[0].severity).toBe(ANOMALY_SEVERITY.Medium);
    resolve(stockoutOnP001().anomaly_id);
    expect(useAnomalyStore.getState().anomalies).toHaveLength(0);
  });
});

describe("anomaly halo", () => {
  let unmount: (() => Promise<void>) | null = null;
  afterEach(async () => {
    await unmount?.();
    unmount = null;
  });

  async function renderScene() {
    const renderer = await ReactThreeTestRenderer.create(<StoreContents store={store} />);
    unmount = () => renderer.unmount();
    const halos = () => {
      const found: InstancedMesh[] = [];
      renderer.scene.instance.traverse((object) => {
        if (object.name.startsWith("stock-anomaly-")) found.push(object as InstancedMesh);
      });
      return found;
    };
    const glows = () =>
      SHAPES.map((shape) => renderer.scene.instance.getObjectByName(`stock-selected-${shape}`) as InstancedMesh | undefined)
        .filter((mesh) => mesh !== undefined);
    const run = (change: () => void) => ReactThreeTestRenderer.act(async () => change());
    return { halos, glows, run };
  }

  const count = (meshes: InstancedMesh[]) => meshes.reduce((sum, mesh) => sum + mesh.count, 0);

  it("puts a halo around the selected P001 when an anomaly event comes in, and keeps the selection glow", async () => {
    const { halos, glows, run } = await renderScene();
    await run(() => useUiStore.getState().select("P001"));
    expect(halos()).toHaveLength(0);
    expect(count(glows())).toBe(drawnOf("P001"));

    await run(() => useAnomalyStore.getState().raise(stockoutOnP001()));
    expect(count(halos())).toBe(drawnOf("P001"));
    const material = halos()[0].material as MeshStandardMaterial;
    expect(material.emissive.equals(new Color(anomalyColor(ANOMALY_SEVERITY.High)))).toBe(true);
    expect(halos()[0].name).toBe(`stock-anomaly-${ANOMALY_SEVERITY.High}-${halos()[0].name.split("-").at(-1)}`);
    expect(halos()[0].castShadow).toBe(false);
    expect(count(glows())).toBe(drawnOf("P001"));

    await run(() => useAnomalyStore.getState().resolve(stockoutOnP001().anomaly_id));
    expect(halos()).toHaveLength(0);
  });

  it("draws a halo for every product with an anomaly, selected or not, and none for a SKU the twin lacks", async () => {
    const { halos, run } = await renderScene();
    const p004 = state.products.find((product) => product.sku === "P004")!;
    await run(() => {
      useAnomalyStore.getState().raise(anomalyFor(p004, ANOMALY_TYPE.SlowMoving, ANOMALY_SEVERITY.Medium, state.context_version));
      useAnomalyStore.getState().raise({ ...stockoutOnP001(), anomaly_id: "anm-gone", sku: "P999" });
    });
    expect(count(halos())).toBe(drawnOf("P004"));
  });

  it("colors a halo by the product's worst open severity", async () => {
    const { halos, run } = await renderScene();
    const low = anomalyFor(p001, ANOMALY_TYPE.SlowMoving, ANOMALY_SEVERITY.Low, state.context_version);
    await run(() => useAnomalyStore.getState().raise(low));
    expect(halos().every((mesh) => mesh.name.startsWith(`stock-anomaly-${ANOMALY_SEVERITY.Low}-`))).toBe(true);
    await run(() => useAnomalyStore.getState().raise(stockoutOnP001()));
    expect(halos().every((mesh) => mesh.name.startsWith(`stock-anomaly-${ANOMALY_SEVERITY.High}-`))).toBe(true);
    expect(count(halos())).toBe(drawnOf("P001"));
    await run(() => useAnomalyStore.getState().raise({ ...stockoutOnP001(), anomaly_id: "anm-critical", severity: ANOMALY_SEVERITY.Critical }));
    expect(halos().every((mesh) => mesh.name.startsWith(`stock-anomaly-${ANOMALY_SEVERITY.Critical}-`))).toBe(true);
  });

  it("draws no halo for an anomaly about a whole shelf", async () => {
    const { halos, run } = await renderScene();
    await run(() => useAnomalyStore.getState().raise({ ...stockoutOnP001(), anomaly_id: "anm-shelf", sku: null }));
    expect(halos()).toHaveLength(0);
  });
});

describe("anomaly in the product card", () => {
  it("shows the anomaly event on P001 next to its twin figures", () => {
    useUiStore.getState().select("P001");
    render(<EntityInspector />);
    const card = screen.getByLabelText("Product P001");
    expect(screen.queryByRole("list", { name: "Open anomalies" })).toBeNull();

    act(() => useAnomalyStore.getState().raise(stockoutOnP001()));
    const list = screen.getByRole("list", { name: "Open anomalies" });
    expect(list.textContent).toContain("Stockout · high");
    expect(list.textContent).not.toContain("older twin state");
    // The figures are the twin's, whatever the anomaly says.
    expect(card.textContent).toContain(`${p001.shelf_id} / ${p001.slot_id}`);
    expect(card.textContent).toContain(String(p001.backroom_quantity));
  });

  it("says when the anomaly was read from an older twin state", () => {
    useAnomalyStore.getState().raise({ ...stockoutOnP001(), context_version: "store-001:v0" });
    useUiStore.getState().select("P001");
    render(<EntityInspector />);
    expect(screen.getByRole("list", { name: "Open anomalies" }).textContent).toContain("read from an older twin state");
  });
});
