import { BoxGeometry, Group, Matrix4, Mesh, MeshStandardMaterial, Quaternion, Vector3 } from "three";
import { describe, expect, it, vi } from "vitest";
import { toSceneStore } from "@/scene/layout";
import { buildStock } from "@/scene/entities/stock/Stock";
import {
  assetsMode,
  clusterOf,
  fitModel,
  productModel,
  toUnitCube,
  type StockModel,
  type StockModels,
} from "@/scene/entities/stock/models";
import { ASSETS_MODE, STOCK_MODEL, type StockModelId } from "@/enums/stock.enum";
import { STOCK_KIND } from "@/enums/scene.enum";
import { stockedStoreState } from "@/test/stockedState";

const store = toSceneStore(stockedStoreState()).store;

const SNACK_NODES = ["Cereal_A", "Cereal_B", "Cereal_C", "Chips_A", "Chips_B", "Chips_D", "Cookies_A", "Cookies_B", "Cookies_C", "Milk_A", "Milk_B", "Juice_A", "Juice_B", "Juice_C"];

/** A stand-in for a loaded model: a unit cube with the given proportions. */
function fakeModel(id: StockModelId, size: [number, number, number]): StockModel {
  return { id, geometry: new BoxGeometry(1, 1, 1), material: new MeshStandardMaterial(), size, grow: 1 };
}

const scaleOf = (matrix: Matrix4) => {
  const scale = new Vector3();
  matrix.decompose(new Vector3(), new Quaternion(), scale);
  return scale;
};

describe("toUnitCube", () => {
  it("centers the geometry in a unit cube and returns its proportions", () => {
    const geometry = new BoxGeometry(0.2, 0.6, 0.1).translate(1, 0.3, 0);
    const size = toUnitCube(geometry);
    expect(size[0]).toBeCloseTo(1 / 3);
    expect(size[1]).toBeCloseTo(1);
    expect(size[2]).toBeCloseTo(1 / 6);
    const box = geometry.boundingBox!;
    expect(box.min.toArray().map((v) => +v.toFixed(6))).toEqual([-0.5, -0.5, -0.5]);
    expect(box.max.toArray().map((v) => +v.toFixed(6))).toEqual([0.5, 0.5, 0.5]);
  });

  it("bakes a turn about Y before measuring", () => {
    const size = toUnitCube(new BoxGeometry(0.4, 0.2, 0.1), [0, Math.PI / 2, 0]);
    expect(size[0]).toBeCloseTo(0.25);
    expect(size[2]).toBeCloseTo(1);
  });
});

describe("clusterOf", () => {
  it("merges fanned, lifted copies of an indexed geometry", () => {
    const one = new BoxGeometry(0.1, 0.1, 0.6);
    const hand = clusterOf(one, [0, 0, 0.3], [{ yaw: -0.4, lift: 0 }, { yaw: 0.4, lift: 0.05 }]);
    expect(hand.getAttribute("position").count).toBe(2 * one.getAttribute("position").count);
    expect(hand.getIndex()!.count).toBe(2 * one.getIndex()!.count);
    expect(Object.keys(hand.attributes).sort()).toEqual(Object.keys(one.attributes).sort());
    hand.computeBoundingBox();
    // Fanned about the stem: wider than one, the same stem end, and lifted.
    expect(hand.boundingBox!.max.x - hand.boundingBox!.min.x).toBeGreaterThan(0.3);
    // Turning about the stem keeps the copies' stem ends near it; the far ends swing out.
    expect(hand.boundingBox!.max.z).toBeLessThan(0.33);
    expect(hand.boundingBox!.max.y).toBeCloseTo(0.1, 5);
  });
});

describe("fitModel", () => {
  it("keeps the model's proportions and fits its tightest side", () => {
    // Width is the tightest: 0.06 / 0.5 = 0.12, under 0.25 / 1 and 0.07 / 0.5.
    fitModel([0.5, 1, 0.5], [0.06, 0.25, 0.07]).forEach((v, i) => expect(v).toBeCloseTo([0.06, 0.12, 0.06][i]));
    const [w, h, d] = fitModel([1, 0.2, 0.8], [0.18, 0.05, 0.14]);
    expect(w).toBeLessThanOrEqual(0.18 + 1e-9);
    expect(h).toBeLessThanOrEqual(0.05 + 1e-9);
    expect(d).toBeLessThanOrEqual(0.14 + 1e-9);
    expect(h / w).toBeCloseTo(0.2);
    expect(d / w).toBeCloseTo(0.8);
  });
});

describe("productModel", () => {
  it("gives a listed product its model only on a surface the model stands on", () => {
    expect(productModel("P007", STOCK_KIND.Packaged)?.model).toBe(STOCK_MODEL.Can);
    // P003 is a jar on the demo gondola, but the sample state puts it in a fruit tray.
    expect(productModel("P003", STOCK_KIND.Fruit)).toBeUndefined();
    expect(productModel("P001", STOCK_KIND.Packaged)?.model).toBe(STOCK_MODEL.CerealTall);
  });

  it("picks an unlisted product's model from its surface's pool, the same every time", () => {
    const fresh = ["meat-raw", "meat-ribs", "meat-sausage", "fish"];
    const picks = Array.from({ length: 40 }, (_, i) => productModel(`P${500 + i}`, STOCK_KIND.Fresh)?.model);
    expect(picks.every((model) => model !== undefined && fresh.includes(model))).toBe(true);
    expect(new Set(picks).size).toBeGreaterThan(1);
    expect(productModel("P512", STOCK_KIND.Fresh)).toEqual(productModel("P512", STOCK_KIND.Fresh));
    // Food keeps its own colors; packaging may take a tint.
    expect(productModel("P512", STOCK_KIND.Fresh)?.tint).toBeUndefined();
    // Every packaged product gets a model; printed packaging is never tinted.
    const packaged = Array.from({ length: 60 }, (_, i) => productModel(`P${600 + i}`, STOCK_KIND.Packaged));
    expect(packaged.every((pick) => pick !== undefined)).toBe(true);
    expect(packaged.filter((pick) => pick!.model.startsWith("snack-")).every((pick) => pick!.tint === undefined)).toBe(true);
  });
});

describe("assetsMode", () => {
  it("is models unless the URL asks for primitives", () => {
    expect(assetsMode("")).toBe(ASSETS_MODE.Models);
    expect(assetsMode("?twin=demo&assets=primitive")).toBe(ASSETS_MODE.Primitive);
    expect(assetsMode("?assets=other")).toBe(ASSETS_MODE.Models);
  });
});

describe("buildStock with models", () => {
  const models: StockModels = new Map([
    [STOCK_MODEL.Can, fakeModel(STOCK_MODEL.Can, [1, 1, 1])],
    [STOCK_MODEL.Apple, fakeModel(STOCK_MODEL.Apple, [1, 1, 1])],
  ]);
  const plain = buildStock(store);
  const modelled = buildStock(store, models);
  const all = (batches: ReturnType<typeof buildStock>) => Object.values(batches).flat();

  it("draws the same items in the same places, batched by model", () => {
    expect(all(modelled)).toHaveLength(all(plain).length);
    const p007 = store.products.find((p) => p.productId === "P007")!;
    const p011 = store.products.find((p) => p.productId === "P011")!;
    expect(modelled[STOCK_MODEL.Can]?.every((item) => item.productId === "P007")).toBe(true);
    const drawnOf = (id: string) => all(plain).filter((item) => item.productId === id).length;
    expect(modelled[STOCK_MODEL.Can]).toHaveLength(drawnOf(p007.productId));
    expect(modelled[STOCK_MODEL.Apple]).toHaveLength(drawnOf(p011.productId));
    // Products whose model did not load keep their primitive.
    expect(modelled.box.some((item) => item.productId === "P005")).toBe(true);
    expect(modelled.box.some((item) => item.productId === "P007")).toBe(false);
  });

  it("stands a model on its cell's floor, no wider than the cell", () => {
    const can = modelled[STOCK_MODEL.Can]![0];
    const box = plain.box.find((item) => item.productId === "P007")!;
    const canScale = scaleOf(can.matrix);
    const boxScale = scaleOf(box.matrix);
    expect(canScale.x).toBeCloseTo(canScale.y);
    expect(canScale.x).toBeLessThanOrEqual(boxScale.x + 1e-9);
    const bottom = (item: typeof can, scale: Vector3) =>
      new Vector3().setFromMatrixPosition(item.matrix).y - scale.y / 2;
    // The primitive's height varies per product; both stand on the same deck.
    expect(bottom(can, canScale)).toBeCloseTo(bottom(box, boxScale), 5);
  });

  it("draws models in white unless tinted, so the texture shows its own colors", () => {
    const can = modelled[STOCK_MODEL.Can]![0];
    expect(Math.abs(can.color.r - can.color.g)).toBeLessThan(1e-6);
  });
});

describe("loadStockModels", () => {
  it("loads each model once into a unit cube, and leaves out one that fails", async () => {
    vi.resetModules();
    const urls: string[] = [];
    vi.doMock("three/examples/jsm/loaders/GLTFLoader.js", () => {
      class GLTFLoader {
        async loadAsync(url: string) {
          urls.push(url);
          if (url.endsWith("banana.glb")) throw new Error("404");
          const scene = new Group();
          // One mesh per file, and named ones for the file that holds several.
          for (const name of ["", ...SNACK_NODES]) {
            const mesh = new Mesh(new BoxGeometry(0.1, 0.3, 0.1), new MeshStandardMaterial({ roughness: 1 }));
            mesh.name = name;
            mesh.position.set(0, 0.15, 0);
            scene.add(mesh);
          }
          return { scene };
        }
      }
      return { GLTFLoader };
    });
    const warn = vi.spyOn(console, "warn").mockImplementation(() => {});
    const { loadStockModels } = await import("@/scene/entities/stock/models");

    const models = await loadStockModels();
    expect(await loadStockModels()).toBe(models);
    // Each file once: the Snackies models share one.
    expect(new Set(urls).size).toBe(urls.length);
    expect(urls.filter((url) => url.endsWith("snackies.glb"))).toHaveLength(1);
    expect(models.has(STOCK_MODEL.BananaBunch)).toBe(false);
    expect(models.get(STOCK_MODEL.CerealTall)).toBeDefined();
    expect(models.size).toBe(Object.values(STOCK_MODEL).length - 1);
    expect(warn).toHaveBeenCalledTimes(1);

    const can = models.get(STOCK_MODEL.Can)!;
    can.geometry.computeBoundingBox();
    expect(can.geometry.boundingBox!.max.y).toBeCloseTo(0.5);
    expect(can.size[1]).toBeCloseTo(1);
    expect(can.size[0]).toBeCloseTo(1 / 3);
    expect(can.material.roughness).toBe(0.6);

    warn.mockRestore();
    vi.doUnmock("three/examples/jsm/loaders/GLTFLoader.js");
  });
});
