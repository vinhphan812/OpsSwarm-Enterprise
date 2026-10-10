import ReactThreeTestRenderer from "@react-three/test-renderer";
import type { ThreeEvent } from "@react-three/fiber";
import { Color, InstancedMesh, Mesh, MeshStandardMaterial, type Intersection, type Object3D } from "three";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { goodColor, selectionColor, warningColor } from "@/core/utils/theme";
import { ENTITY_TYPE } from "@/enums/scene.enum";
import { stockedStoreState } from "@/test/stockedState";
import { useSelectOnClick } from "@/hooks/selectEntity.hook";
import { toSceneStore } from "@/scene/layout";
import { StoreContents } from "@/scene/StoreScene";
import { buildStock } from "@/scene/entities/stock/Stock";
import { isSelected, selectedProductId, useUiStore } from "@/state/ui.store";

// The app has no checkout data until apps/api serves it: CK01 open, CK02 paused, CK03 closed here.
vi.mock("@/hooks/checkout.hook", async () => {
  const { SAMPLE_CHECKOUTS } = await import("@/test/checkoutSample");
  return { useCheckoutSummary: (id: string) => SAMPLE_CHECKOUTS[id] ?? null, useCheckoutTransactions: () => [] };
});

const store = toSceneStore(stockedStoreState()).store;
const glow = new Color(selectionColor());

function meshesUnder(root: Object3D): Mesh[] {
  const meshes: Mesh[] = [];
  root.traverse((object) => {
    // Hit boxes are hidden, and a lane light keeps its status color.
    const mesh = object as Mesh;
    if (mesh.isMesh && (mesh.material as MeshStandardMaterial).visible && !mesh.userData.keepColor) meshes.push(mesh);
  });
  return meshes;
}

const glows = (mesh: Mesh) => {
  const material = mesh.material as MeshStandardMaterial;
  return material.emissive?.equals(glow) === true;
};

async function render() {
  const renderer = await ReactThreeTestRenderer.create(<StoreContents store={store} />);
  const find = (name: string) => renderer.scene.instance.getObjectByName(name)!;
  const select = (id: string | null, type?: (typeof ENTITY_TYPE)[keyof typeof ENTITY_TYPE]) =>
    ReactThreeTestRenderer.act(async () => useUiStore.getState().select(id, type));
  return { find, select };
}

beforeEach(() => useUiStore.getState().select(null));

describe("ui store selection", () => {
  it("selects a product by default, and a fixture when told", () => {
    const { select } = useUiStore.getState();
    select("P001");
    expect(selectedProductId(useUiStore.getState())).toBe("P001");
    select("A01", ENTITY_TYPE.Shelf);
    expect(isSelected(useUiStore.getState(), "A01", ENTITY_TYPE.Shelf)).toBe(true);
    expect(selectedProductId(useUiStore.getState())).toBeNull();
    select(null);
    expect(useUiStore.getState()).toMatchObject({ selectedEntityId: null, selectedEntityType: null });
  });
});

describe("selection glow", () => {
  it("draws the selected product's items again, glowing, and nothing else", async () => {
    const { find, select } = await render();
    expect(find("stock-selected-box")).toBeUndefined();

    await select("P002");
    const p002 = stockedStoreState().products.find((product) => product.sku === "P002")!;
    const overlay = find("stock-selected-box") as InstancedMesh;
    expect(overlay.count).toBe(p002.shelf_quantity);
    expect(glows(overlay)).toBe(true);
    expect(overlay.castShadow).toBe(false);

    await select(null);
    expect(find("stock-selected-box")).toBeUndefined();
  });

  it("lights up a selected shelf and gives its parts their own materials back", async () => {
    const { find, select } = await render();
    const before = meshesUnder(find("A01")).map((mesh) => mesh.material);
    expect(meshesUnder(find("A01")).some(glows)).toBe(false);

    await select("A01", ENTITY_TYPE.Shelf);
    expect(meshesUnder(find("A01")).every(glows)).toBe(true);
    expect(meshesUnder(find("A02")).some(glows)).toBe(false);
    // The shared materials themselves are untouched.
    expect(before.some((material) => (material as MeshStandardMaterial).emissive?.equals(glow))).toBe(false);

    await select(null);
    expect(meshesUnder(find("A01")).map((mesh) => mesh.material)).toEqual(before);
  });

  it("lights up a selected checkout, not a shelf with the same id type", async () => {
    const { find, select } = await render();
    const lamp = () => find("CK01").getObjectByName("lane-lamp") as Mesh;
    const before = lamp().material as MeshStandardMaterial;
    await select("CK01", ENTITY_TYPE.Equipment);
    expect(meshesUnder(find("CK01")).every(glows)).toBe(true);
    // The lane light keeps telling the lane's status, and burns brighter.
    const lit = lamp().material as MeshStandardMaterial;
    expect(lit.emissive.equals(before.emissive)).toBe(true);
    expect(lit.emissiveIntensity).toBeGreaterThan(before.emissiveIntensity);
    await select(null);
    expect(lamp().material).toBe(before);
    expect(meshesUnder(find("CK02")).some(glows)).toBe(false);
    // A product selected under the same id would not light the checkout.
    await select("CK01");
    expect(meshesUnder(find("CK01")).some(glows)).toBe(false);
  });
});

describe("fixture click", () => {
  const items = buildStock(store).box;
  const a01Item = items.findIndex((item) => item.holderId === "A01");
  const a02Item = items.findIndex((item) => item.holderId === "A02");
  const stockHit = (instanceId: number) =>
    ({ object: { userData: { stockItems: items } }, instanceId }) as unknown as Intersection;

  function click(hits: Intersection[], delta = 0) {
    let stopped = false;
    const event = { delta, intersections: hits, stopPropagation: () => (stopped = true) };
    useSelectOnClick("A01", ENTITY_TYPE.Shelf)(event as unknown as ThreeEvent<MouseEvent>);
    return stopped;
  }

  it("selects the shelf, unless the click is on one of its own items", () => {
    expect(click([stockHit(a02Item)])).toBe(true);
    expect(isSelected(useUiStore.getState(), "A01", ENTITY_TYPE.Shelf)).toBe(true);

    useUiStore.getState().select(null);
    expect(click([stockHit(a01Item)])).toBe(false);
    expect(useUiStore.getState().selectedEntityId).toBeNull();
  });

  it("ignores a camera drag", () => {
    expect(click([], 20)).toBe(false);
    expect(useUiStore.getState().selectedEntityId).toBeNull();
  });
});

describe("lane light", () => {
  it("is lit green while open, amber while paused, and dark while closed or unknown", async () => {
    const { find } = await render();
    const lamp = (id: string) => (find(id).getObjectByName("lane-lamp") as Mesh).material as MeshStandardMaterial;
    expect(find("CK01").getObjectByName("lane-light")!.userData.status).toBe("open");
    expect(lamp("CK01").emissive.equals(new Color(goodColor()))).toBe(true);
    expect(lamp("CK02").emissive.equals(new Color(warningColor()))).toBe(true);
    expect(lamp("CK03").emissive.getHex()).toBe(0x000000);
  });
});
