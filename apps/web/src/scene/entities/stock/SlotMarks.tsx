import { useFrame } from "@react-three/fiber";
import { useMemo } from "react";
import {
  BoxGeometry,
  EdgesGeometry,
  LineBasicMaterial,
  Matrix4,
  MeshBasicMaterial,
  Quaternion,
  Vector3,
} from "three";
import { CHANGE_CUE_MS } from "@/constants/twin.constant";
import { ANOMALY_SEVERITY } from "@/enums/anomaly.enum";
import { ENTITY_TYPE, type FixtureKind } from "@/enums/scene.enum";
import { useRecentChanges } from "@/hooks/recentChanges.hook";
import { prefersReducedMotion } from "@/core/utils/motion";
import { anomalyColor, changeColor, selectionColor } from "@/core/utils/theme";
import { entityMatrix } from "@/scene/utils/transform";
import { changedSkus, type StateDiff } from "@/core/twin/stateDiff";
import { useProposalChanges } from "@/hooks/activeTwin.hook";
import type { RecentChange } from "@/state/twin.store";
import type { SlotFixture, StockSurface, StoreFixture } from "@/types/scene.type";
import { slotCapacity } from "./capacity";
import { stockItemFor } from "./catalog";
import { surfaceMatrix, surfacesOf } from "./surfaces";

/** A product's slot as a box over its surface, as tall as the clear height: a unit cube moved by `matrix`. */
export type SlotBox = { productId: string; slotId: string; matrix: Matrix4 };

export type SlotMarks = {
  /** Slots holding more facings than they fit. */
  overflow: SlotBox[];
  /** Slots whose product's facings changed in `change`, or whose shelf gained units. */
  changed: SlotBox[];
  /** Slots the proposal on screen changes: where a changed product stands, and where a moved one stood. */
  proposed: SlotBox[];
};

type Holder = { kind: FixtureKind; matrix: Matrix4; slots: Map<string, SlotFixture> };

function holdersOf(store: StoreFixture): Map<string, Holder> {
  const holders = new Map<string, Holder>();
  for (const shelf of store.shelves) {
    holders.set(shelf.shelfId, {
      kind: ENTITY_TYPE.Shelf,
      matrix: entityMatrix(shelf.position, shelf.rotationY),
      slots: new Map(shelf.slots.map((slot) => [slot.slotId, slot])),
    });
  }
  for (const item of store.equipment) {
    holders.set(item.equipmentId, {
      kind: item.kind,
      matrix: entityMatrix(item.position, item.rotationY),
      slots: new Map(item.slots.map((slot) => [slot.slotId, slot])),
    });
  }
  return holders;
}

type PlacedSlot = { holder: Holder; slot: SlotFixture; surface: StockSurface };

/** Slot `slotId` of fixture `shelfId` with its surface, or null when the layout has no such slot. */
function placedSlot(holders: Map<string, Holder>, shelfId: string, slotId: string): PlacedSlot | null {
  const holder = holders.get(shelfId);
  const slot = holder?.slots.get(slotId);
  const surface = holder && slot ? surfacesOf(holder.kind)[slot.surface] : undefined;
  return holder && slot && surface ? { holder, slot, surface } : null;
}

function slotBox({ holder, slot, surface }: PlacedSlot, productId: string): SlotBox {
  return {
    productId,
    slotId: slot.slotId,
    matrix: new Matrix4()
      .multiplyMatrices(holder.matrix, surfaceMatrix(surface))
      .multiply(
        new Matrix4().compose(
          new Vector3(slot.offset, surface.maxHeight / 2, 0),
          new Quaternion(),
          new Vector3(slot.width, surface.maxHeight, surface.depth),
        ),
      ),
  };
}

/**
 * The slots of `store`, the state on screen, to mark: every overflowing slot, the slots
 * of the facings changes in `change` whose product still has the new facings, or of the
 * shelf gains in `change` whose product still has the new shelf count, and the slots
 * `proposal` (the proposal on screen against Live) changes.
 */
export function slotMarksOf(store: StoreFixture, change: RecentChange | null, proposal: StateDiff | null = null): SlotMarks {
  const marks: SlotMarks = { overflow: [], changed: [], proposed: [] };
  const holders = holdersOf(store);
  const changed = new Map(change?.diff.facings.map((item) => [item.sku, item.after]));
  const before = new Map(change?.before.products.map((item) => [item.sku, item.shelf_quantity]));
  const restocked = new Map(
    change?.diff.quantity
      .filter((item) => item.shelfDelta > 0 && before.has(item.sku))
      .map((item) => [item.sku, before.get(item.sku)! + item.shelfDelta]),
  );
  const proposed = new Set(proposal ? changedSkus(proposal) : []);
  for (const product of store.products) {
    const placed = placedSlot(holders, product.shelfId, product.slotId);
    if (!placed) continue;
    const box = () => slotBox(placed, product.productId);
    if (product.facings > slotCapacity(placed.slot, stockItemFor(placed.surface.kind))) marks.overflow.push(box());
    if (changed.get(product.productId) === product.facings || restocked.get(product.productId) === product.shelfQuantity) {
      marks.changed.push(box());
    }
    if (proposed.has(product.productId)) marks.proposed.push(box());
  }
  for (const move of proposal?.moved ?? []) {
    const source = placedSlot(holders, move.from.shelf_id, move.from.slot_id);
    if (source) marks.proposed.push(slotBox(source, move.sku));
  }
  return marks;
}

const UNIT_BOX = new BoxGeometry(1, 1, 1);
const UNIT_EDGES = new EdgesGeometry(UNIT_BOX);
/** Strongest opacity of the change glow, at the moment of the change. */
const CHANGE_GLOW_OPACITY = 0.45;
const OVERFLOW_FILL_OPACITY = 0.18;

/** Made on first use, once the theme stylesheet has loaded. */
let materials: {
  edge: LineBasicMaterial;
  fill: MeshBasicMaterial;
  glow: MeshBasicMaterial;
  proposed: LineBasicMaterial;
} | null = null;
function markMaterials() {
  const overflow = anomalyColor(ANOMALY_SEVERITY.High);
  materials ??= {
    edge: new LineBasicMaterial({ color: overflow }),
    fill: new MeshBasicMaterial({ color: overflow, transparent: true, opacity: OVERFLOW_FILL_OPACITY, depthWrite: false }),
    glow: new MeshBasicMaterial({ color: selectionColor(), transparent: true, opacity: CHANGE_GLOW_OPACITY, depthWrite: false }),
    proposed: new LineBasicMaterial({ color: changeColor() }),
  };
  return materials;
}

/** Marks take no clicks: a click goes through to the item or fixture behind. */
const NO_RAYCAST = () => null;

/**
 * Slot marks over the stock. An overflowing slot is outlined in red, with a faint red
 * fill, for as long as it overflows; it is never drawn as a valid slot. A recent facings
 * change or shelf gain (`useRecentChanges`) glows on its slot and fades over `CHANGE_CUE_MS`;
 * with reduced motion it holds still until the cue ends. In the Simulation view every slot
 * the proposal changes (`useProposalChanges`) is outlined for as long as the proposal is on
 * screen, the source slot of a move included.
 */
export function SlotMarksLayer({ store }: { store: StoreFixture }) {
  const change = useRecentChanges();
  const proposal = useProposalChanges();
  const marks = useMemo(() => slotMarksOf(store, change, proposal), [store, change, proposal]);
  const motion = useMemo(() => !prefersReducedMotion(), []);
  const { edge, fill, glow, proposed } = markMaterials();

  useFrame(() => {
    if (!change || marks.changed.length === 0) return;
    const left = motion ? 1 - Math.min(1, (Date.now() - change.at) / CHANGE_CUE_MS) : 1;
    glow.opacity = CHANGE_GLOW_OPACITY * left;
  });

  return (
    <group name="slot-marks">
      {marks.overflow.map(({ slotId, matrix }) => (
        <group key={`overflow-${slotId}`} name={`slot-overflow-${slotId}`} matrix={matrix} matrixAutoUpdate={false}>
          <lineSegments geometry={UNIT_EDGES} material={edge} raycast={NO_RAYCAST} />
          <mesh geometry={UNIT_BOX} material={fill} raycast={NO_RAYCAST} renderOrder={1} />
        </group>
      ))}
      {marks.proposed.map(({ productId, slotId, matrix }) => (
        <lineSegments
          key={`proposed-${productId}-${slotId}`}
          name={`slot-proposed-${slotId}`}
          matrix={matrix}
          matrixAutoUpdate={false}
          geometry={UNIT_EDGES}
          material={proposed}
          raycast={NO_RAYCAST}
        />
      ))}
      {marks.changed.map(({ slotId, matrix }) => (
        <mesh
          key={`changed-${slotId}`}
          name={`slot-changed-${slotId}`}
          matrix={matrix}
          matrixAutoUpdate={false}
          geometry={UNIT_BOX}
          material={glow}
          raycast={NO_RAYCAST}
          renderOrder={1}
        />
      ))}
    </group>
  );
}
