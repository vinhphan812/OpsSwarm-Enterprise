import { Box3, Matrix4, Quaternion, Vector3 } from "three";
import { MOVE_ARC_HEIGHT, MOVE_ARRIVAL_FLASH, MOVE_SLOT_HANDOFF } from "@/constants/scene.constant";
import { MOVE_MARK_IN_MS, MOVE_MARK_OUT_MS, MOVE_TWEEN_MS } from "@/constants/twin.constant";
import { ENTITY_TYPE } from "@/enums/scene.enum";
import type { ProductMove, SlotRef } from "@/core/twin/stateDiff";
import { entityMatrix } from "@/scene/utils/transform";
import type { RecentChange } from "@/state/twin.store";
import type { ProductFixture, SlotFixture, StockSurface, StoreFixture } from "@/types/scene.type";
import { surfaceMatrix, surfacesOf } from "./surfaces";

/**
 * The scene's cue for the moves of a recent change. `offsets` take each moved product's
 * items from their destination back to their source slot; `ghost` is what stood at the
 * source before the move, and `sources` the frame of each source slot's surface, to
 * outline it in; `fromSlots` and `toSlots` are the source and destination slots to light up.
 */
export type MoveCue = {
  at: number;
  offsets: Map<string, Vector3>;
  ghost: StoreFixture;
  sources: Map<string, Matrix4>;
  fromSlots: Matrix4[];
  toSlots: Matrix4[];
};

/** How thick the light laid over a moved product's slots is, in meters. */
const SLOT_LIGHT_THICKNESS = 0.012;

type SlotFrame = { toWorld: Matrix4; slot: SlotFixture; surface: StockSurface };

/** A slot's surface frame in world space, or null when the layout has no such slot. */
function slotFrame(store: StoreFixture, { shelf_id, slot_id }: SlotRef): SlotFrame | null {
  const shelf = store.shelves.find((item) => item.shelfId === shelf_id);
  const holder = shelf
    ? { kind: ENTITY_TYPE.Shelf, fixture: shelf }
    : store.equipment.map((item) => ({ kind: item.kind, fixture: item })).find(({ fixture }) => fixture.equipmentId === shelf_id);
  const slot = holder?.fixture.slots.find((item) => item.slotId === slot_id);
  const surface = holder && slot ? surfacesOf(holder.kind)[slot.surface] : undefined;
  if (!holder || !slot || !surface) return null;
  const toWorld = entityMatrix(holder.fixture.position, holder.fixture.rotationY).multiply(surfaceMatrix(surface));
  return { toWorld, slot, surface };
}

/** Middle of a slot's front edge on its surface, in world space. */
function slotCenter({ toWorld, slot }: SlotFrame): Vector3 {
  return new Vector3(slot.offset, 0, 0).applyMatrix4(toWorld);
}

/** A thin slab over the whole slot, just above its surface. */
function slotLight({ toWorld, slot, surface }: SlotFrame): Matrix4 {
  const local = new Matrix4().compose(
    new Vector3(slot.offset, SLOT_LIGHT_THICKNESS / 2, 0),
    new Quaternion(),
    new Vector3(slot.width, SLOT_LIGHT_THICKNESS, surface.depth),
  );
  return toWorld.clone().multiply(local);
}

/**
 * The cue for the moves in `change` on `store`, the state on screen, or null when there
 * is none to show. A move counts only while the product still stands where the move put
 * it and both slots are in the layout.
 */
export function moveCueOf(store: StoreFixture, change: RecentChange | null): MoveCue | null {
  if (!change || change.diff.moved.length === 0) return null;
  const placed = new Map(store.products.map((product) => [product.productId, product]));
  const shown: ProductMove[] = [];
  const offsets = new Map<string, Vector3>();
  const sources = new Map<string, Matrix4>();
  const fromSlots: Matrix4[] = [];
  const toSlots: Matrix4[] = [];
  for (const move of change.diff.moved) {
    const product = placed.get(move.sku);
    if (product?.shelfId !== move.to.shelf_id || product.slotId !== move.to.slot_id) continue;
    const from = slotFrame(store, move.from);
    const to = slotFrame(store, move.to);
    if (!from || !to) continue;
    shown.push(move);
    offsets.set(move.sku, slotCenter(from).sub(slotCenter(to)));
    sources.set(move.sku, from.toWorld);
    fromSlots.push(slotLight(from));
    toSlots.push(slotLight(to));
  }
  if (shown.length === 0) return null;
  // Not `toSceneStore`: the layout module imports the stock surfaces, which import this one.
  const moved = new Set(shown.map((move) => move.sku));
  const before: ProductFixture[] = change.before.products
    .filter((product) => moved.has(product.sku))
    .map((product) => ({
      productId: product.sku,
      shelfId: product.shelf_id,
      slotId: product.slot_id,
      facings: product.facings,
      shelfQuantity: product.shelf_quantity,
      backroomQuantity: product.backroom_quantity,
      version: product.version,
    }));
  return { at: change.at, offsets, ghost: { ...store, products: before }, sources, fromSlots, toSlots };
}

/** How far a move's tween has come at `now`, from 0 to 1. */
export function moveProgress(at: number, now: number): number {
  return Math.min(1, Math.max(0, (now - at) / MOVE_TWEEN_MS));
}

const clamp01 = (t: number) => Math.min(1, Math.max(0, t));
const easeInOut = (t: number) => (t < 0.5 ? 4 * t * t * t : 1 - (-2 * t + 2) ** 3 / 2);

/**
 * `matrix` shifted back toward its source by what is left of the tween at `progress`,
 * and lifted on an arc up to `MOVE_ARC_HEIGHT` midway, so the items hop over the shelf
 * edge rather than slide through it; written into `out`. At 1 it is `matrix` itself:
 * the end of the tween is the state.
 */
export function tweenMatrix(matrix: Matrix4, offset: Vector3, progress: number, out = new Matrix4()): Matrix4 {
  const done = easeInOut(clamp01(progress));
  const left = 1 - done;
  const lift = MOVE_ARC_HEIGHT * 4 * done * left;
  return out.makeTranslation(offset.x * left, offset.y * left + lift, offset.z * left).multiply(matrix);
}

/**
 * One box per moved product around the items it had at its source slot, squared to the
 * slot's surface: the outline the scene draws where the product stood. `items` are the
 * ghost's drawn items, each a unit box under its matrix.
 */
export function ghostOutlines(cue: MoveCue, items: { matrix: Matrix4; productId: string }[]): Matrix4[] {
  const boxes = new Map<string, Box3>();
  const corner = new Vector3();
  const toLocal = new Matrix4();
  const local = new Matrix4();
  for (const item of items) {
    const frame = cue.sources.get(item.productId);
    if (!frame) continue;
    const box = boxes.get(item.productId) ?? new Box3();
    local.multiplyMatrices(toLocal.copy(frame).invert(), item.matrix);
    for (const x of [-0.5, 0.5]) for (const y of [-0.5, 0.5]) for (const z of [-0.5, 0.5]) {
      box.expandByPoint(corner.set(x, y, z).applyMatrix4(local));
    }
    boxes.set(item.productId, box);
  }
  return [...boxes].map(([sku, box]) => {
    const size = box.getSize(new Vector3());
    const local = new Matrix4().compose(box.getCenter(new Vector3()), new Quaternion(), size);
    return cue.sources.get(sku)!.clone().multiply(local);
  });
}

/**
 * True while the outline and slot lights of a move appeared at `at` still show at `now`:
 * while the items travel, then `MOVE_MARK_OUT_MS` more to fade out. With reduced motion
 * there is no fade, so they go the moment the items would have arrived.
 */
export function marksShown(at: number, now: number, motion = true): boolean {
  return now - at < MOVE_TWEEN_MS + (motion ? MOVE_MARK_OUT_MS : 0);
}

/** How strongly each mark of a move shows, from 0 to 1; `flash` is the destination's extra glow. */
export type MarkLevels = { ghost: number; from: number; to: number; flash: number };

/** Every mark at full strength and no flash: what reduced motion shows while the marks are up. */
export const STEADY_MARKS: MarkLevels = { ghost: 1, from: 1, to: 1, flash: 0 };

/**
 * The marks of a move appeared at `at`, at `now`. They fade in over `MOVE_MARK_IN_MS`.
 * While the items travel the light hands over: the source slot dims and the destination
 * brightens. When the items land the destination flashes, and everything fades out over
 * `MOVE_MARK_OUT_MS`.
 */
export function markLevels(at: number, now: number): MarkLevels {
  const elapsed = now - at;
  const fadeIn = clamp01(elapsed / MOVE_MARK_IN_MS);
  const fadeOut = 1 - clamp01((elapsed - MOVE_TWEEN_MS) / MOVE_MARK_OUT_MS);
  const level = fadeIn * fadeOut;
  const done = easeInOut(moveProgress(at, now));
  return {
    ghost: level,
    from: level * (1 - MOVE_SLOT_HANDOFF * done),
    to: level * (1 - MOVE_SLOT_HANDOFF * (1 - done)),
    flash: elapsed >= MOVE_TWEEN_MS ? MOVE_ARRIVAL_FLASH * fadeOut : 0,
  };
}
