import { Box3, Vector3, type Mesh, type Object3D } from "three";
import type { Tuple3 } from "@/types/scene.type";

/** Where the decor GLB files are served from (`public/models`). See `assets/3d/README.md`. */
const MODEL_DIR = `${import.meta.env.BASE_URL}models/`;

/**
 * How big a piece is drawn: its height in meters (plants, furniture, buildings), its width
 * along its own X in meters (a mat), or a scale per axis of the model's own units (road and
 * pavement tiles, stretched to length).
 */
export type DecorFit = { height: number } | { width: number } | { scale: Tuple3 };

/**
 * One piece of decor: a GLB file (relative to `public/models`), where it stands (x, z in
 * meters, store frame), its turn about Y, and its size. Its base is centered on that point and
 * set on the ground at `y` (0 is the shop floor).
 */
export type DecorItem = {
  id: string;
  file: string;
  at: [x: number, z: number];
  rotationY?: number;
  fit: DecorFit;
  y?: number;
};

/** A loaded decor file: its scene, to be cloned per placement, and its size in its own units. */
export type DecorModel = { scene: Object3D; size: Tuple3; base: Tuple3 };
export type DecorModels = ReadonlyMap<string, DecorModel>;
export const NO_DECOR: DecorModels = new Map();

/** The scale `fit` asks of a model of `size`, and the offset that stands its base, centered, on the origin. */
export function fitDecor(size: Tuple3, base: Tuple3, fit: DecorFit): { scale: Tuple3; offset: Tuple3 } {
  let scale: Tuple3;
  if ("scale" in fit) scale = fit.scale;
  else {
    const [extent, wanted] = "height" in fit ? [size[1], fit.height] : [size[0], fit.width];
    const uniform = extent > 0 ? wanted / extent : 1;
    scale = [uniform, uniform, uniform];
  }
  return { scale, offset: [-base[0] * scale[0], -base[1] * scale[1], -base[2] * scale[2]] };
}

/**
 * Decor takes no pointer events, so a plant in front of a shelf never swallows the click
 * meant for it, and it casts and takes shadows like the fixtures.
 */
export function prepareDecor(scene: Object3D): DecorModel {
  scene.updateMatrixWorld(true);
  const box = new Box3().setFromObject(scene);
  const size = box.getSize(new Vector3());
  // The base point: the center of the model's footprint, at its lowest point.
  const base: Tuple3 = [(box.min.x + box.max.x) / 2, box.min.y, (box.min.z + box.max.z) / 2];
  scene.traverse((object) => {
    object.raycast = () => {};
    if ((object as Mesh).isMesh) {
      object.castShadow = true;
      object.receiveShadow = true;
    }
  });
  return { scene, size: [size.x, size.y, size.z], base };
}

/**
 * Every decor file, loaded once per page. A file that fails is left out (and logged), so its
 * pieces are simply not drawn.
 */
let loaded: Promise<DecorModels> | null = null;
export function loadDecor(items: readonly DecorItem[]): Promise<DecorModels> {
  loaded ??= import("three/examples/jsm/loaders/GLTFLoader.js")
    .then(({ GLTFLoader }) => {
      const loader = new GLTFLoader();
      const files = [...new Set(items.map((item) => item.file))];
      return Promise.allSettled(
        files.map(async (file) => [file, prepareDecor((await loader.loadAsync(`${MODEL_DIR}${file}`)).scene)] as const),
      );
    })
    .then((results) => {
      const models = new Map<string, DecorModel>();
      for (const result of results) {
        if (result.status === "fulfilled") models.set(result.value[0], result.value[1]);
        else console.warn("Decor model not loaded; its pieces are left out.", result.reason);
      }
      return models;
    })
    .catch((error: unknown) => {
      console.warn("Decor not loaded.", error);
      return NO_DECOR;
    });
  return loaded;
}
