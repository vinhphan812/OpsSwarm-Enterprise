import { Matrix4 } from "three";
import { ARRIVAL_OVERSHOOT } from "@/constants/scene.constant";
import { ARRIVAL_GROW_MS, ARRIVAL_SPREAD_MS } from "@/constants/twin.constant";
import type { RecentChange } from "@/state/twin.store";

/**
 * The scene's cue for the items a recent change adds: `from` holds, per product, how many
 * items it had drawn before the change. Its items ranked at or past that grow in.
 */
export type ArrivalCue = { at: number; from: Map<string, number>; added: Map<string, number> };

/**
 * The products of `change` that may have gained drawn items: more facings, more shelf
 * stock, or new in the state. A moved product travels instead (`moveCueOf`), so it is left out.
 */
export function gainedSkus(change: RecentChange | null): Set<string> {
  if (!change) return new Set();
  const moved = new Set(change.diff.moved.map((move) => move.sku));
  const skus = [
    ...change.diff.facings.filter((item) => item.after > item.before).map((item) => item.sku),
    ...change.diff.quantity.filter((item) => item.shelfDelta > 0).map((item) => item.sku),
    ...change.diff.added,
  ];
  return new Set(skus.filter((sku) => !moved.has(sku)));
}

/**
 * The cue for `change`, from each gained product's drawn item count before it (`before`)
 * and now (`after`), or null when no product draws more items than it did.
 */
export function arrivalCueOf(
  change: RecentChange | null,
  before: Map<string, number>,
  after: Map<string, number>,
): ArrivalCue | null {
  if (!change) return null;
  const from = new Map<string, number>();
  const added = new Map<string, number>();
  for (const sku of gainedSkus(change)) {
    const was = before.get(sku) ?? 0;
    const now = after.get(sku) ?? 0;
    if (now <= was) continue;
    from.set(sku, was);
    added.set(sku, now - was);
  }
  return from.size === 0 ? null : { at: change.at, from, added };
}

/**
 * How far the `nth` of `count` new items has grown at `now`, from 0 to 1. The items start
 * one after another across `ARRIVAL_SPREAD_MS`, and each takes `ARRIVAL_GROW_MS`.
 */
export function arrivalProgress(at: number, now: number, nth: number, count: number): number {
  const start = count > 1 ? (ARRIVAL_SPREAD_MS * nth) / (count - 1) : 0;
  return Math.min(1, Math.max(0, (now - at - start) / ARRIVAL_GROW_MS));
}

/** True once every item of a cue that started at `at` has grown in. */
export function arrivalDone(at: number, now: number): boolean {
  return now - at >= ARRIVAL_SPREAD_MS + ARRIVAL_GROW_MS;
}

const easeOutBack = (t: number) => {
  const c = ARRIVAL_OVERSHOOT;
  return 1 + (c + 1) * (t - 1) ** 3 + c * (t - 1) ** 2;
};
/** Kept above zero, so an item that has not started is a speck, never a degenerate matrix. */
const MIN_SCALE = 1e-3;
const grow = new Matrix4();
const toFloor = new Matrix4().makeTranslation(0, -0.5, 0);
const fromFloor = new Matrix4().makeTranslation(0, 0.5, 0);

/**
 * `matrix` (a unit item) scaled about the middle of its bottom face by how far it has grown
 * at `progress`, a little past full size before it settles, so it rises from its shelf;
 * written into `out`. At 1 it is `matrix` itself: the end of the cue is the state.
 */
export function growMatrix(matrix: Matrix4, progress: number, out = new Matrix4()): Matrix4 {
  if (progress >= 1) return out.copy(matrix);
  const scale = Math.max(MIN_SCALE, easeOutBack(Math.max(0, progress)));
  grow.makeScale(scale, scale, scale);
  return out.copy(matrix).multiply(toFloor).multiply(grow).multiply(fromFloor);
}
