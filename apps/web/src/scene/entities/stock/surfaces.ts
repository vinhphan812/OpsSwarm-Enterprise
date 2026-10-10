import { Euler, Matrix4, Quaternion, Vector3 } from "three";
import { ENTITY_TYPE, EQUIPMENT_KIND, type FixtureKind } from "@/enums/scene.enum";
import { GLASS_DOOR_COOLER_SURFACES } from "@/scene/entities/equipment/GlassDoorCooler";
import { OPEN_CHILLER_SURFACES } from "@/scene/entities/equipment/OpenChiller";
import { PRODUCE_RACK_SURFACES } from "@/scene/entities/equipment/ProduceRack";
import { SHELF_SURFACES } from "@/scene/entities/Shelf";
import type { StockSurface } from "@/types/scene.type";

/** Display surfaces of every fixture kind that holds products. Crates and barriers hold none: they are decor, not shelves. */
const SURFACES: Partial<Record<FixtureKind, StockSurface[]>> = {
  [ENTITY_TYPE.Shelf]: SHELF_SURFACES,
  [EQUIPMENT_KIND.ProduceRack]: PRODUCE_RACK_SURFACES,
  [EQUIPMENT_KIND.GlassDoorCooler]: GLASS_DOOR_COOLER_SURFACES,
  [EQUIPMENT_KIND.OpenChiller]: OPEN_CHILLER_SURFACES,
};

export function surfacesOf(kind: FixtureKind): StockSurface[] {
  return SURFACES[kind] ?? [];
}

/** Surfaces are module constants, so each matrix is computed once. */
const matrices = new WeakMap<StockSurface, Matrix4>();

/**
 * Surface frame to fixture frame: turn about Y, then tilt about the surface's own X.
 * The matrix is shared; clone it before changing it.
 */
export function surfaceMatrix(surface: StockSurface): Matrix4 {
  let matrix = matrices.get(surface);
  if (!matrix) {
    matrix = new Matrix4().compose(
      new Vector3(...surface.center),
      new Quaternion().setFromEuler(new Euler(surface.tilt ?? 0, surface.rotationY ?? 0, 0, "YXZ")),
      new Vector3(1, 1, 1),
    );
    matrices.set(surface, matrix);
  }
  return matrix;
}

/** A point given in a surface's own frame, in the fixture's frame. */
export function surfacePoint(surface: StockSurface, x: number, y: number, z: number): Vector3 {
  return new Vector3(x, y, z).applyMatrix4(surfaceMatrix(surface));
}
