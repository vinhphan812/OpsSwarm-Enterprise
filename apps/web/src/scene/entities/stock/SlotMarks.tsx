import { useFrame } from "@react-three/fiber";
import { useLayoutEffect, useMemo, useRef } from "react";
import {
  BoxGeometry,
  EdgesGeometry,
  InstancedMesh,
  LineBasicMaterial,
  Matrix4,
  MeshBasicMaterial,
  Quaternion,
  Vector3,
} from "three";
import { CHANGE_CUE_MS } from "@/constants/twin.constant";
import { ANOMALY_SEVERITY } from "@/enums/anomaly.enum";
import { ENTITY_TYPE, type FixtureKind } from "@/enums/scene.enum";
import { OVERLAY, RISK_BANDS, type RiskBand } from "@/enums/ui.enum";
import { useRecentChanges } from "@/hooks/recentChanges.hook";
import { prefersReducedMotion } from "@/core/utils/motion";
import { anomalyColor, changeColor, riskBandColor, selectionColor } from "@/core/utils/theme";
import { entityMatrix } from "@/scene/utils/transform";
import { changedSkus, type StateDiff } from "@/core/twin/stateDiff";
import { useProposalChanges } from "@/hooks/activeTwin.hook";
import { useStockoutRisk } from "@/hooks/stockoutRisk.hook";
import { riskBandsBySku } from "@/core/twin/stockoutRisk";
import { useUiStore } from "@/state/ui.store";
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

/** The slots of `store` whose product has a stockout-risk band, by band; a product without one is left out. */
export function riskSlotsOf(store: StoreFixture, bands: ReadonlyMap<string, RiskBand>): Record<RiskBand, SlotBox[]> {
  const slots = Object.fromEntries(RISK_BANDS.map((band) => [band, [] as SlotBox[]])) as Record<RiskBand, SlotBox[]>;
  const holders = holdersOf(store);
  for (const product of store.products) {
    const band = bands.get(product.productId);
    const placed = band ? placedSlot(holders, product.shelfId, product.slotId) : null;
    if (band && placed) slots[band].push(slotBox(placed, product.productId));
  }
  return slots;
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
 * screen, the source slot of a move included. Turning the AI changes overlay off hides both.
 */
export function SlotMarksLayer({ store }: { store: StoreFixture }) {
  const aiChanges = useUiStore((state) => state.overlays[OVERLAY.AiChanges]);
  const recent = useRecentChanges();
  const shownProposal = useProposalChanges();
  // With the AI changes overlay off, a change neither glows nor is outlined; overflow still shows.
  const change = aiChanges ? recent : null;
  const proposal = aiChanges ? shownProposal : null;
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

/** Fill opacity by band: the low band is faint, so the riskier slots stand out of a mostly green store. */
const RISK_FILL_OPACITY: Record<RiskBand, number> = { low: 0.12, elevated: 0.3, high: 0.4, severe: 0.5 };

/** Made on first use, once the theme stylesheet has loaded. */
let riskMaterials: Record<RiskBand, MeshBasicMaterial> | null = null;
function riskMaterialOf(band: RiskBand) {
  riskMaterials ??= Object.fromEntries(
    RISK_BANDS.map((item) => [
      item,
      new MeshBasicMaterial({ color: riskBandColor(item), transparent: true, opacity: RISK_FILL_OPACITY[item], depthWrite: false }),
    ]),
  ) as Record<RiskBand, MeshBasicMaterial>;
  return riskMaterials[band];
}

/** One band's slots as instances of a unit box, named `stockout-risk-<band>`, with their slot ids in `userData`. */
function RiskBandMesh({ band, slots }: { band: RiskBand; slots: SlotBox[] }) {
  const ref = useRef<InstancedMesh>(null);
  useLayoutEffect(() => {
    const mesh = ref.current;
    if (!mesh) return;
    slots.forEach(({ matrix }, index) => mesh.setMatrixAt(index, matrix));
    mesh.count = slots.length;
    mesh.instanceMatrix.needsUpdate = true;
    mesh.computeBoundingSphere();
  }, [slots]);
  return (
    <instancedMesh
      // A new mesh when the count grows past what it was made for.
      key={slots.length}
      ref={ref}
      name={`stockout-risk-${band}`}
      args={[UNIT_BOX, riskMaterialOf(band), slots.length]}
      userData={{ slotIds: slots.map((slot) => slot.slotId) }}
      raycast={NO_RAYCAST}
      renderOrder={1}
    />
  );
}

/**
 * The stockout-risk overlay (#213): while it is on, each slot whose product has a served
 * stockout risk (`useStockoutRisk`) is tinted by its band, green, yellow, orange, or red
 * (`stockoutRiskBand`). A product without one stays as it is. Nothing is drawn while the
 * overlay is off or no risk is served (Live, until apps/api serves it).
 */
export function StockoutRiskLayer({ store }: { store: StoreFixture }) {
  const on = useUiStore((state) => state.overlays[OVERLAY.StockoutRisk]);
  const risks = useStockoutRisk();
  const slots = useMemo(() => (on && risks ? riskSlotsOf(store, riskBandsBySku(risks)) : null), [on, risks, store]);
  if (!slots) return null;
  return (
    <group name="stockout-risk">
      {RISK_BANDS.map((band) => (slots[band].length ? <RiskBandMesh key={band} band={band} slots={slots[band]} /> : null))}
    </group>
  );
}
