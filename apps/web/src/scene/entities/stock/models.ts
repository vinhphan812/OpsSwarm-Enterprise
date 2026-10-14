import { Box3, BufferAttribute, Cache, Vector3, type BufferGeometry, type Mesh, type MeshStandardMaterial, type Object3D } from "three";
import { STOCK_KIND, type StockKind } from "@/enums/scene.enum";
import { ASSETS_MODE, STOCK_MODEL, type AssetsMode, type StockModelId } from "@/enums/stock.enum";
import type { Tuple3 } from "@/types/scene.type";
import { idFraction } from "./catalog";

/** Where the GLB files are served from (`public/models`). See `assets/3d/README.md`. */
const MODEL_DIR = `${import.meta.env.BASE_URL}models/`;
const KENNEY = "kenney-food/";
const SNACKIES = "snackies/snackies.glb";

/**
 * A GLB model and the surfaces it may stand on. `rotation` lays the model down (about X,
 * then Z) and turns its broad side to the front of the shelf (about Y, +Z); it is baked into
 * the geometry when it loads. `grow` lets a model reach past its cell. `layout` lays loose
 * produce out in bigger cells than an apple's, in fewer layers, turned at most `jitter` off
 * square instead of every which way. `tint` is the color multiplied over the
 * texture when the product has none of its own. `node` names the mesh in a file that holds
 * several; `printed` marks packaging art, which is never tinted.
 */
type ModelSpec = {
  file: string;
  node?: string;
  printed?: boolean;
  kinds: readonly StockKind[];
  rotation?: Tuple3;
  grow?: number;
  layout?: StockLayout;
  tint?: string;
  /** Copies of the mesh fanned about Y around `pivot` and lifted by `lift`, merged into one (`clusterOf`). */
  cluster?: { pivot: Tuple3; parts: ReadonlyArray<{ yaw: number; lift: number }> };
};

/** How loose produce lies (`ModelSpec.layout`): its cell as a multiple of the display item's, the heap's layers, and the most it turns off square, in radians. */
export type StockLayout = { cell: number; layers: number; jitter: number };

const TURN = Math.PI / 2;

const MODEL_SPEC: Record<StockModelId, ModelSpec> = {
  [STOCK_MODEL.Apple]: { file: `${KENNEY}apple.glb`, kinds: [STOCK_KIND.Fruit] },
  [STOCK_MODEL.Bag]: { file: `${KENNEY}bag.glb`, kinds: [STOCK_KIND.Packaged], rotation: [0, TURN, 0] },
  [STOCK_MODEL.BagFlat]: { file: `${KENNEY}bag-flat.glb`, kinds: [STOCK_KIND.Frozen] },
  // The pack has one banana; four of them fanned from the stem (its square end, at +Z) make a
  // hand. Hands lie side by side in one layer, alternate ends to the aisle; a heap of them
  // reads as a tangle. The texture's pale yellow reads white under the lights.
  [STOCK_MODEL.BananaBunch]: {
    file: `${KENNEY}banana.glb`,
    kinds: [STOCK_KIND.Fruit],
    cluster: {
      pivot: [0, 0.17, 0.3],
      parts: [
        { yaw: -0.42, lift: 0 },
        { yaw: -0.14, lift: 0.05 },
        { yaw: 0.14, lift: 0.05 },
        { yaw: 0.42, lift: 0 },
      ],
    },
    layout: { cell: 1.6, layers: 1, jitter: 0.25 },
    tint: "#ffd23f",
  },
  [STOCK_MODEL.BottleOil]: { file: `${KENNEY}bottle-oil.glb`, kinds: [STOCK_KIND.Packaged] },
  [STOCK_MODEL.Can]: { file: `${KENNEY}can.glb`, kinds: [STOCK_KIND.Packaged] },
  // On its side, head to the left.
  [STOCK_MODEL.Fish]: { file: `${KENNEY}fish.glb`, kinds: [STOCK_KIND.Fresh], rotation: [0, TURN, TURN] },
  [STOCK_MODEL.IceCreamTub]: { file: `${KENNEY}ice-cream-cup.glb`, kinds: [STOCK_KIND.Frozen] },
  // Lying flat, stick to the side.
  [STOCK_MODEL.IceLolly]: { file: `${KENNEY}popsicle.glb`, kinds: [STOCK_KIND.Frozen], rotation: [0, 0, TURN] },
  [STOCK_MODEL.Jar]: { file: `${KENNEY}honey.glb`, kinds: [STOCK_KIND.Packaged] },
  [STOCK_MODEL.Lemon]: { file: `${KENNEY}lemon.glb`, kinds: [STOCK_KIND.Fruit] },
  [STOCK_MODEL.MeatTray]: { file: `${KENNEY}meat-raw.glb`, kinds: [STOCK_KIND.Fresh], rotation: [0, TURN, 0] },
  [STOCK_MODEL.Orange]: { file: `${KENNEY}orange.glb`, kinds: [STOCK_KIND.Fruit] },
  [STOCK_MODEL.PeanutButter]: { file: `${KENNEY}peanut-butter.glb`, kinds: [STOCK_KIND.Packaged] },
  [STOCK_MODEL.Ribs]: { file: `${KENNEY}meat-ribs.glb`, kinds: [STOCK_KIND.Fresh] },
  [STOCK_MODEL.Sausages]: { file: `${KENNEY}meat-sausage.glb`, kinds: [STOCK_KIND.Fresh], rotation: [0, TURN, 0] },
  [STOCK_MODEL.CerealTall]: snack("Cereal_A"),
  [STOCK_MODEL.CerealWide]: snack("Cereal_B"),
  [STOCK_MODEL.CerealFamily]: snack("Cereal_C"),
  [STOCK_MODEL.ChipsClassic]: snack("Chips_A"),
  [STOCK_MODEL.ChipsOriginal]: snack("Chips_B"),
  [STOCK_MODEL.ChipsChunky]: snack("Chips_D"),
  [STOCK_MODEL.CookiesBox]: snack("Cookies_A"),
  [STOCK_MODEL.BiscuitsBox]: snack("Cookies_B"),
  [STOCK_MODEL.CookiesTube]: snack("Cookies_C"),
  [STOCK_MODEL.MilkBlue]: snack("Milk_A"),
  [STOCK_MODEL.MilkGreen]: snack("Milk_B"),
  [STOCK_MODEL.JuiceSmall]: snack("Juice_A"),
  [STOCK_MODEL.JuiceSlim]: snack("Juice_B"),
  [STOCK_MODEL.JuiceTall]: snack("Juice_C"),
};

/** A Snackies pack on the gondolas, printed side to the aisle. */
function snack(node: string): ModelSpec {
  return { file: SNACKIES, node, kinds: [STOCK_KIND.Packaged], printed: true };
}

/** A product's model, and a color multiplied over the model's own texture. */
type ProductModel = { model: StockModelId; tint?: string };

/** `PRODUCT_MODEL` value for a product drawn as its primitive. */
const PRIMITIVE = null;

/**
 * Models for the named demo catalog (`DEMO_NAMES`). Twin state carries no product looks, so
 * this is presentation only, like `productLook`. A product listed for a surface its model
 * does not stand on keeps its primitive.
 */
const PRODUCT_MODEL: Readonly<Record<string, ProductModel | typeof PRIMITIVE>> = {
  P001: { model: STOCK_MODEL.CerealTall },
  P002: { model: STOCK_MODEL.BiscuitsBox },
  P003: { model: STOCK_MODEL.PeanutButter },
  P004: { model: STOCK_MODEL.Bag, tint: "#f6d77a" },
  P005: { model: STOCK_MODEL.BottleOil },
  P006: { model: STOCK_MODEL.Jar, tint: "#8a5a3c" },
  P007: { model: STOCK_MODEL.Can },
  P008: { model: STOCK_MODEL.Bag },
  P009: { model: STOCK_MODEL.MeatTray },
  P010: { model: STOCK_MODEL.BagFlat, tint: "#9ccc65" },
  P011: { model: STOCK_MODEL.Apple },
  P012: { model: STOCK_MODEL.BananaBunch },
  P013: { model: STOCK_MODEL.Ribs },
  P014: { model: STOCK_MODEL.Sausages },
  P015: { model: STOCK_MODEL.Fish },
  P016: { model: STOCK_MODEL.IceCreamTub },
  P018: { model: STOCK_MODEL.IceLolly },
  P020: { model: STOCK_MODEL.BagFlat, tint: "#f2c14e" },
};

/** What an unlisted product may look like on each kind of surface. Repeats weigh a pick. */
const MODEL_POOL: Record<StockKind, readonly StockModelId[]> = {
  [STOCK_KIND.Packaged]: [
    STOCK_MODEL.CerealTall,
    STOCK_MODEL.CerealWide,
    STOCK_MODEL.CerealFamily,
    STOCK_MODEL.ChipsClassic,
    STOCK_MODEL.ChipsOriginal,
    STOCK_MODEL.ChipsChunky,
    STOCK_MODEL.CookiesBox,
    STOCK_MODEL.BiscuitsBox,
    STOCK_MODEL.CookiesTube,
    STOCK_MODEL.MilkBlue,
    STOCK_MODEL.MilkGreen,
    STOCK_MODEL.JuiceSmall,
    STOCK_MODEL.JuiceSlim,
    STOCK_MODEL.JuiceTall,
    STOCK_MODEL.Can,
    STOCK_MODEL.Jar,
    STOCK_MODEL.PeanutButter,
    STOCK_MODEL.BottleOil,
    STOCK_MODEL.Bag,
  ],
  [STOCK_KIND.Fruit]: [STOCK_MODEL.Apple, STOCK_MODEL.Orange, STOCK_MODEL.Lemon, STOCK_MODEL.BananaBunch],
  [STOCK_KIND.Fresh]: [STOCK_MODEL.MeatTray, STOCK_MODEL.Ribs, STOCK_MODEL.Sausages, STOCK_MODEL.Fish],
  [STOCK_KIND.Frozen]: [STOCK_MODEL.BagFlat, STOCK_MODEL.IceCreamTub, STOCK_MODEL.IceLolly],
};

/** Light tints over packaging, so brands that share a model read apart; food keeps its own colors. */
const PACK_TINTS = ["#ffffff", "#ffffff", "#ffd6d6", "#d6e6ff", "#dcf3d2", "#fff0c4", "#e8d8ff"] as const;
const TINTED: ReadonlySet<StockKind> = new Set([STOCK_KIND.Packaged, STOCK_KIND.Frozen]);

/**
 * The model a product is drawn with on a surface of `kind`, if it has one there. A product
 * not in `PRODUCT_MODEL` (the demo's filler stock, or any SKU from apps/api) takes one from
 * `MODEL_POOL` by its id: stable across reloads, but not data.
 */
export function productModel(productId: string, kind: StockKind): ProductModel | undefined {
  if (productId in PRODUCT_MODEL) {
    const entry = PRODUCT_MODEL[productId];
    return entry && MODEL_SPEC[entry.model].kinds.includes(kind) ? entry : undefined;
  }
  const pool = MODEL_POOL[kind];
  const model = pool[Math.floor(idFraction(productId, 2) * pool.length)];
  if (!model) return undefined;
  const tinted = TINTED.has(kind) && !MODEL_SPEC[model].printed;
  const tint = tinted ? PACK_TINTS[Math.floor(idFraction(productId, 3) * PACK_TINTS.length)] : undefined;
  return { model, tint };
}

/**
 * A loaded model, ready to instance: geometry centered on the origin and scaled to a unit
 * cube like the primitives, and `size`, its proportions with the longest side 1.
 */
export type StockModel = {
  id: StockModelId;
  geometry: BufferGeometry;
  material: MeshStandardMaterial;
  size: Tuple3;
  /** How far past its cell the model is drawn (`ModelSpec.grow`). */
  grow: number;
  layout?: StockLayout;
  tint?: string;
};

export type StockModels = ReadonlyMap<StockModelId, StockModel>;
export const NO_MODELS: StockModels = new Map();

/** Turns `geometry` by `rotation` (X, then Z, then Y), then centers it and scales it to a unit cube, in place. Returns its proportions. */
export function toUnitCube(geometry: BufferGeometry, [x, y, z]: Tuple3 = [0, 0, 0]): Tuple3 {
  if (x) geometry.rotateX(x);
  if (z) geometry.rotateZ(z);
  if (y) geometry.rotateY(y);
  geometry.computeBoundingBox();
  const box = geometry.boundingBox ?? new Box3();
  const size = box.getSize(new Vector3());
  const center = box.getCenter(new Vector3());
  geometry.translate(-center.x, -center.y, -center.z);
  geometry.scale(1 / size.x, 1 / size.y, 1 / size.z);
  geometry.computeBoundingBox();
  geometry.computeBoundingSphere();
  const longest = Math.max(size.x, size.y, size.z);
  return [size.x / longest, size.y / longest, size.z / longest];
}

/**
 * Copies of an indexed `geometry`, each turned by `yaw` about the Y axis through `pivot` and
 * raised by `lift`, merged into one geometry with the same attributes.
 */
export function clusterOf(
  geometry: BufferGeometry,
  pivot: Tuple3,
  parts: ReadonlyArray<{ yaw: number; lift: number }>,
): BufferGeometry {
  const copies = parts.map(({ yaw, lift }) =>
    geometry.clone().translate(-pivot[0], -pivot[1], -pivot[2]).rotateY(yaw).translate(pivot[0], pivot[1] + lift, pivot[2]),
  );
  const merged = geometry.clone();
  for (const name of Object.keys(geometry.attributes)) {
    const { itemSize, normalized } = geometry.getAttribute(name);
    const arrays = copies.map((copy) => copy.getAttribute(name).array as Float32Array);
    const joined = new Float32Array(arrays.reduce((n, array) => n + array.length, 0));
    arrays.reduce((offset, array) => (joined.set(array, offset), offset + array.length), 0);
    merged.setAttribute(name, new BufferAttribute(joined, itemSize, normalized));
  }
  const index = geometry.getIndex();
  if (index) {
    const count = geometry.getAttribute("position").count;
    const joined = new Uint32Array(index.count * parts.length);
    parts.forEach((_, k) => {
      for (let i = 0; i < index.count; i += 1) joined[k * index.count + i] = index.getX(i) + k * count;
    });
    merged.setIndex(new BufferAttribute(joined, 1));
  }
  for (const copy of copies) copy.dispose();
  return merged;
}

/** The largest size, in the model's proportions, that fits inside `cell`. */
export function fitModel(size: Tuple3, cell: Tuple3): Tuple3 {
  const scale = Math.min(cell[0] / size[0], cell[1] / size[1], cell[2] / size[2]);
  return [size[0] * scale, size[1] * scale, size[2] * scale];
}

/**
 * The mesh named `node` in a loaded GLB scene, or its first mesh, with its node transform
 * baked into the geometry.
 */
function meshOf(scene: Object3D, node?: string): Mesh | undefined {
  scene.updateMatrixWorld(true);
  let found: Mesh | undefined;
  scene.traverse((object) => {
    if (!found && (object as Mesh).isMesh && (node === undefined || object.name === node)) found = object as Mesh;
  });
  if (found) found.geometry.applyMatrix4(found.matrixWorld);
  return found;
}

type GltfLoader = { loadAsync(url: string): Promise<{ scene: Object3D }> };
/** Loads a file once, however many models read it. */
type LoadFile = (file: string) => Promise<{ scene: Object3D }>;

async function loadModel(loadFile: LoadFile, id: StockModelId): Promise<StockModel> {
  const spec = MODEL_SPEC[id];
  const gltf = await loadFile(spec.file);
  const mesh = meshOf(gltf.scene, spec.node);
  const material = mesh?.material as MeshStandardMaterial | undefined;
  if (!mesh || !material || Array.isArray(mesh.material) || !material.isMeshStandardMaterial) {
    throw new Error(`${spec.file}${spec.node ? `#${spec.node}` : ""}: expected one mesh with one standard material`);
  }
  const source = mesh.geometry;
  // No normal map, so the tangents are never read.
  source.deleteAttribute("tangent");
  const geometry = spec.cluster ? clusterOf(source, spec.cluster.pivot, spec.cluster.parts) : source;
  if (geometry !== source) source.dispose();
  const size = toUnitCube(geometry, spec.rotation);
  // Kenney and Snackies export fully rough; match the primitives' sheen under the studio lights.
  material.roughness = 0.6;
  return { id, geometry, material, size, grow: spec.grow ?? 1, layout: spec.layout, tint: spec.tint };
}

/**
 * Every model, loaded once per page and shared by every mount of the scene, like the
 * primitives. A model that fails to load is left out (and logged), so its products keep
 * their primitive and the rest of the scene is unaffected.
 */
let loaded: Promise<StockModels> | null = null;
export function loadStockModels(): Promise<StockModels> {
  // The loader is imported on demand, so it stays out of the first bundle.
  loaded ??= import("three/examples/jsm/loaders/GLTFLoader.js")
    .then(({ GLTFLoader }) => {
      const loader: GltfLoader = new GLTFLoader();
      const files = new Map<string, Promise<{ scene: Object3D }>>();
      const loadFile: LoadFile = (file) => {
        let gltf = files.get(file);
        if (!gltf) {
          gltf = loader.loadAsync(`${MODEL_DIR}${file}`);
          files.set(file, gltf);
        }
        return gltf;
      };
      // Kenney's models read the same texture atlas; with the cache on, it is fetched once, not once per model.
      const caching = Cache.enabled;
      Cache.enabled = true;
      return Promise.allSettled(Object.values(STOCK_MODEL).map((id) => loadModel(loadFile, id))).finally(() => {
        Cache.enabled = caching;
      });
    })
    .then((results) => {
      const models = new Map<StockModelId, StockModel>();
      for (const result of results) {
        if (result.status === "fulfilled") models.set(result.value.id, result.value);
        else console.warn("Stock model not loaded; its products stay primitives.", result.reason);
      }
      return models;
    })
    .catch((error: unknown) => {
      console.warn("Stock models not loaded; stock stays primitives.", error);
      return NO_MODELS;
    });
  return loaded;
}

/** `?assets=primitive` draws every stock item as a primitive and loads no models. */
export function assetsMode(search = window.location.search): AssetsMode {
  return new URLSearchParams(search).get("assets") === ASSETS_MODE.Primitive
    ? ASSETS_MODE.Primitive
    : ASSETS_MODE.Models;
}
