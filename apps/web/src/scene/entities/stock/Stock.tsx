import type { Intersection } from "three";
import { useFrame, useThree, type ThreeEvent } from "@react-three/fiber";
import { useEffect, useLayoutEffect, useMemo, useRef } from "react";
import {
  BoxGeometry,
  Color,
  CylinderGeometry,
  EdgesGeometry,
  IcosahedronGeometry,
  LineBasicMaterial,
  Matrix4,
  MeshBasicMaterial,
  MeshStandardMaterial,
  Quaternion,
  Vector3,
  type BufferGeometry,
  type Group,
  type InstancedMesh,
  type Material,
  type QuadraticBezierCurve3,
} from "three";
import { selectedProductId, useUiStore } from "@/state/ui.store";
import { MOVE_MARK_HOLD_SIMULATION_MS } from "@/constants/twin.constant";
import { VIEW_MODE } from "@/enums/ui.enum";
import { worstSeverities } from "@/state/anomaly.store";
import { useShownAnomalies } from "@/hooks/activeTwin.hook";
import { useRecentChanges } from "@/hooks/recentChanges.hook";
import { ANOMALY_SEVERITIES, type AnomalySeverity } from "@/enums/anomaly.enum";
import { prefersReducedMotion } from "@/core/utils/motion";
import {
  ANOMALY_HALO_GLOW,
  ANOMALY_HALO_OPACITY,
  ANOMALY_PULSE_DEPTH,
  ANOMALY_PULSE_HZ,
  MOVE_GHOST_FILL_OPACITY,
  MOVE_GHOST_OPACITY,
  MOVE_SLOT_GLOW,
  MOVE_SLOT_OPACITY,
  SELECTION_ITEM_GLOW,
} from "@/constants/scene.constant";
import { anomalyColor, changeColor, selectionColor } from "@/core/utils/theme";
import { ENTITY_TYPE, STOCK_KIND, type FixtureKind } from "@/enums/scene.enum";
import { isDrag } from "@/scene/utils/pointer";
import type {
  SlotFixture,
  StockSurface,
  StoreFixture,
  Tuple3,
} from "@/types/scene.type";
import { entityMatrix } from "@/scene/utils/transform";
import { STOCK_SHAPE, type StockShape } from "@/enums/stock.enum";
import {
  displayItemFor,
  idFraction,
  productLook,
  stockItemFor,
} from "./catalog";
import { slotCapacity } from "./capacity";
import { MoveArrows, showArrows } from "./MoveArrows";
import { fitItem, layItems, slotUnits, type Emit } from "./placement";
import {
  ghostOutlines,
  markLevels,
  marksShown,
  moveCueOf,
  moveProgress,
  STEADY_MARKS,
  storeBefore,
  tweenMatrix,
  type MarkLevels,
  type MoveCue,
} from "./moveCue";
import { arrivalCueOf, arrivalDone, arrivalProgress, gainedSkus, growMatrix, type ArrivalCue } from "./arrivalCue";
import { surfaceMatrix, surfacesOf } from "./surfaces";
import { NO_MODELS, fitModel, productModel, type StockLayout, type StockModel, type StockModels } from "./models";
import type { StockModelId } from "@/enums/stock.enum";

const GEOMETRY: Record<StockShape, BufferGeometry> = {
  [STOCK_SHAPE.Box]: new BoxGeometry(1, 1, 1),
  [STOCK_SHAPE.Cylinder]: new CylinderGeometry(0.5, 0.5, 1, 10),
  [STOCK_SHAPE.Sphere]: new IcosahedronGeometry(0.5, 1),
};

/** White base; each instance carries its own color. */
const STOCK_MATERIAL = new MeshStandardMaterial({
  color: "#ffffff",
  roughness: 0.6,
});
/**
 * The selected product's items, drawn again over the stock: their own colors, lit up.
 * Made on first use, once the theme stylesheet has loaded.
 */
let selectedMaterial: MeshStandardMaterial | null = null;
function selectedItemMaterial() {
  selectedMaterial ??= new MeshStandardMaterial({
    color: "#ffffff",
    roughness: 0.6,
    emissive: selectionColor(),
    emissiveIntensity: SELECTION_ITEM_GLOW,
  });
  return selectedMaterial;
}
/** A model's material, lit up like `selectedItemMaterial`; one copy per model material. */
const selectedModelMaterials = new WeakMap<Material, MeshStandardMaterial>();
function selectedMaterialOf(model: StockModel | undefined): Material {
  if (!model) return selectedItemMaterial();
  let material = selectedModelMaterials.get(model.material);
  if (!material) {
    material = model.material.clone();
    material.emissive = new Color(selectionColor());
    material.emissiveIntensity = SELECTION_ITEM_GLOW;
    selectedModelMaterials.set(model.material, material);
  }
  return material;
}
/** The glowing copy is a little larger, so it covers the item without z-fighting. */
const SELECTED_SCALE = new Matrix4().makeScale(1.04, 1.04, 1.04);

/**
 * A see-through shell around each item of a product with an open anomaly, in its worst
 * severity's color. It sits outside the selection glow, so a selected product with an
 * anomaly shows both. One material per severity, made on first use; `pulseHalos` breathes them.
 */
const haloMaterials = new Map<AnomalySeverity, MeshStandardMaterial>();
function anomalyHaloMaterial(severity: AnomalySeverity) {
  let material = haloMaterials.get(severity);
  if (!material) {
    material = new MeshStandardMaterial({
      color: anomalyColor(severity),
      emissive: anomalyColor(severity),
      emissiveIntensity: ANOMALY_HALO_GLOW,
      transparent: true,
      opacity: ANOMALY_HALO_OPACITY,
      depthWrite: false,
    });
    haloMaterials.set(severity, material);
  }
  return material;
}

/** Brightens and dims every halo together; `wave` runs from -1 to 1. */
function pulseHalos(wave: number) {
  const factor = 1 + ANOMALY_PULSE_DEPTH * wave;
  for (const material of haloMaterials.values()) {
    material.opacity = Math.min(0.9, ANOMALY_HALO_OPACITY * factor);
    material.emissiveIntensity = ANOMALY_HALO_GLOW * factor;
  }
}
const ANOMALY_SCALE = new Matrix4().makeScale(1.12, 1.12, 1.12);

/** Items are drawn a little under their footprint, so neighbours show a seam between them. */
const ITEM_INSET = 0.92;
const UP = new Vector3(0, 1, 0);
/** Brightness spread between items of one product, so a facing does not read as flat plastic. */
const SHADE_SPREAD = 0.12;

/** One drawn item. `holderId` is the shelf or equipment it stands on; `rank` is its place among its product's items, from 0. */
type Placed = {
  matrix: Matrix4;
  color: Color;
  productId: string;
  holderId: string;
  rank: number;
};
/** Items are batched per primitive shape, and per GLB model for products drawn with one. */
type BatchKey = StockShape | StockModelId;
type Batches = Record<StockShape, Placed[]> & Partial<Record<StockModelId, Placed[]>>;

type Holder = {
  matrix: Matrix4;
  surfaces: StockSurface[];
  slots: Map<string, SlotFixture>;
};

/**
 * Every product drawn at its slot, symbolically: items at their display size
 * (`displayItemFor`), bigger and fewer than the units they stand for, in the share of the
 * slot its facings take, filled as far as its shelf stock fills what the facings hold
 * (`slotUnits`). Any stock at all draws at least one item. Nothing is drawn for zero
 * facings or zero stock. A product whose shelf or slot is unknown is skipped;
 * `toSceneStore` reports those before they get here.
 *
 * A product with a loaded model (`productModel`) is drawn with it: in the model's own
 * proportions, as large as fits the item's cell, standing on the cell's floor. A model
 * with a `layout` (bananas) lies in its own bigger cells.
 */
export function buildStock(store: StoreFixture, models: StockModels = NO_MODELS): Batches {
  const batches: Batches = { box: [], cylinder: [], sphere: [] };
  const holders = new Map<string, Holder>();
  for (const shelf of store.shelves) {
    holders.set(shelf.shelfId, {
      matrix: entityMatrix(shelf.position, shelf.rotationY),
      surfaces: surfacesOf(ENTITY_TYPE.Shelf),
      slots: new Map(shelf.slots.map((slot) => [slot.slotId, slot])),
    });
  }
  for (const item of store.equipment) {
    holders.set(item.equipmentId, {
      matrix: entityMatrix(item.position, item.rotationY),
      surfaces: surfacesOf(item.kind),
      slots: new Map(item.slots.map((slot) => [slot.slotId, slot])),
    });
  }

  // Reused per item; only the final world matrix is kept.
  const scratch = {
    pos: new Vector3(),
    quat: new Quaternion(),
    scale: new Vector3(),
    local: new Matrix4(),
  };
  for (const product of store.products) {
    const holder = holders.get(product.shelfId);
    const slot = holder?.slots.get(product.slotId);
    const surface = slot ? holder?.surfaces[slot.surface] : undefined;
    if (!holder || !slot || !surface) continue;

    const natural = stockItemFor(surface.kind);
    const capacity = slotCapacity(slot, natural);
    // Never more than the slot holds; `toSceneStore` reports the overflow.
    const facings = Math.min(Math.max(0, product.facings), capacity);
    const held = slotUnits(surface, slot, facings);
    const drawnWith = productModel(product.productId, surface.kind);
    const model = drawnWith ? models.get(drawnWith.model) : undefined;
    const layout = model?.layout;
    const shown = displayItemFor(surface.kind, layout?.cell);
    const shownCapacity = slotCapacity(slot, shown);
    const shownFacings = facings === 0 ? 0 : Math.max(1, Math.min(shownCapacity, Math.round((facings * shownCapacity) / capacity)));
    const item = fitItem(shown, surface);
    const look = productLook(item, product.productId);
    // A model brings its own colors and height; a tint, if any, is multiplied over them.
    const base = new Color(model ? (drawnWith?.tint ?? model.tint ?? "#ffffff") : look.color);
    const heightShare = model ? 1 : look.height;
    const key: BatchKey = model ? model.id : item.shape;
    const [w, h, d] = item.size;
    const height = h * heightShare;
    const inset = item.shape === STOCK_SHAPE.Sphere ? 1 : ITEM_INSET;
    const cell: Tuple3 = [w * inset, height, d * inset];
    const scale = model ? fitModel(model.size, cell).map((v) => v * model.grow) as Tuple3 : cell;
    // Loose produce lies every which way; packaging keeps facing the aisle.
    const tumbles = model !== undefined && surface.kind === STOCK_KIND.Fruit;
    let full = 0;
    layItems(surface, slot, item, shownFacings, () => (full += 1), layout?.layers);
    // Lowers a model shorter than its cell onto the cell's floor.
    const drop = (height - scale[1]) / 2;
    let index = 0;
    const toWorld = new Matrix4().multiplyMatrices(
      holder.matrix,
      surfaceMatrix(surface),
    );
    let stock =
      held > 0 && product.shelfQuantity > 0 ? Math.max(1, Math.ceil((full * Math.min(held, product.shelfQuantity)) / held)) : 0;
    const emit: Emit = ([x, y, z]) => {
      if (stock <= 0) return;
      stock -= 1;
      index += 1;
      // Scaling y with the height keeps a shorter product standing on its surface and its stack.
      scratch.local.compose(
        scratch.pos.set(x, y * heightShare - drop, z),
        tumbles
          ? scratch.quat.setFromAxisAngle(UP, turnOf(product.productId, index, layout))
          : scratch.quat.identity(),
        scratch.scale.set(...scale),
      );
      const shade =
        1 + (idFraction(product.productId, index + 1) - 0.5) * SHADE_SPREAD;
      (batches[key] ??= []).push({
        matrix: new Matrix4().multiplyMatrices(toWorld, scratch.local),
        color: base.clone().multiplyScalar(shade),
        productId: product.productId,
        holderId: product.shelfId,
        rank: index - 1,
      });
    };
    layItems(surface, slot, item, shownFacings, emit, layout?.layers);
  }
  return batches;
}

/** How far loose produce turns about Y: any way for round fruit; for a `layout`, alternate ends to the aisle, `jitter` off square. */
function turnOf(productId: string, index: number, layout: StockLayout | undefined): number {
  const r = idFraction(productId, index + 7);
  return layout ? (index % 2) * Math.PI + (r - 0.5) * 2 * layout.jitter : r * Math.PI * 2;
}

const heldCounts = new WeakMap<StoreFixture, Map<string, number>>();

/**
 * How many shelf units of each product its facings hold: its shelf stock, up to what
 * the facings take at the item's natural size (`slotUnits`). `buildStock` draws stock
 * symbolically, so this is the count, not the number of items drawn. Computed once per
 * store object.
 */
export function unitsHeld(store: StoreFixture): Map<string, number> {
  let counts = heldCounts.get(store);
  if (!counts) {
    counts = new Map();
    const holders = new Map<string, { kind: FixtureKind; slots: SlotFixture[] }>([
      ...store.shelves.map((shelf) => [shelf.shelfId, { kind: ENTITY_TYPE.Shelf as FixtureKind, slots: shelf.slots }] as const),
      ...store.equipment.map((item) => [item.equipmentId, { kind: item.kind as FixtureKind, slots: item.slots }] as const),
    ]);
    for (const product of store.products) {
      const holder = holders.get(product.shelfId);
      const slot = holder?.slots.find((candidate) => candidate.slotId === product.slotId);
      const surface = holder && slot ? surfacesOf(holder.kind)[slot.surface] : undefined;
      if (!slot || !surface) continue;
      const facings = Math.min(Math.max(0, product.facings), slotCapacity(slot, stockItemFor(surface.kind)));
      const held = Math.min(Math.max(0, product.shelfQuantity), slotUnits(surface, slot, facings));
      if (held > 0) counts.set(product.productId, (counts.get(product.productId) ?? 0) + held);
    }
    heldCounts.set(store, counts);
  }
  return counts;
}

/** How many items `batches` draws of each product. */
export function drawnCounts(batches: Batches): Map<string, number> {
  const counts = new Map<string, number>();
  for (const items of Object.values(batches)) {
    for (const item of items ?? []) counts.set(item.productId, (counts.get(item.productId) ?? 0) + 1);
  }
  return counts;
}

/** The stock item a raycast hit, if it hit one. Fixture hit boxes use it to let their own items take a click. */
export function stockItemAt(hit: Intersection): Placed | undefined {
  const items = hit.object.userData.stockItems as Placed[] | undefined;
  return items && hit.instanceId !== undefined
    ? items[hit.instanceId]
    : undefined;
}

/** Where an item is drawn; the default is where the state puts it. */
type MatrixOf = (item: Placed) => Matrix4;
const atState: MatrixOf = (item) => item.matrix;

/** Reused by every tween frame; `setMatrixAt` copies it. */
const tweened = new Matrix4();

/** The cues that draw items away from the state for a moment: moves travel, gained items grow in. */
type ItemCues = { move: MoveCue | null; arrival: ArrivalCue | null };
const NO_CUES: ItemCues = { move: null, arrival: null };

/** Where `item` is drawn at `now` under `cues`, written into `tweened`; null when it stands at the state. */
function cuedMatrix(item: Placed, base: Matrix4, cues: ItemCues, now: number): Matrix4 | null {
  const offset = cues.move?.offsets.get(item.productId);
  if (offset) return tweenMatrix(base, offset, moveProgress(cues.move!.at, now), tweened);
  const arrival = cues.arrival;
  const from = arrival?.from.get(item.productId);
  if (!arrival || from === undefined || item.rank < from) return null;
  const progress = arrivalProgress(arrival.at, now, item.rank - from, arrival.added.get(item.productId) ?? 1);
  return growMatrix(base, progress, tweened);
}

/**
 * Draws the items under a cue away from the state, from when the cue appeared: a moved
 * product's items travel from its source slot over `MOVE_TWEEN_MS`, and the items a product
 * gains grow in one after another. The layout effect has already drawn them at the state;
 * each frame of a cue draws them on the way there, and its last frame draws the state again.
 * A cue cut short (a newer state, another view) is put back at the state too, so the scene
 * never stays between two states.
 */
function useCueTween(
  ref: { current: InstancedMesh | null },
  items: Placed[],
  matrixOf: MatrixOf,
  cues: ItemCues,
) {
  const running = useRef(false);
  useLayoutEffect(() => {
    running.current = cues.move !== null || cues.arrival !== null;
    return () => {
      const mesh = ref.current;
      if (!running.current || !mesh) return;
      running.current = false;
      items.forEach((item, index) => mesh.setMatrixAt(index, matrixOf(item)));
      mesh.instanceMatrix.needsUpdate = true;
    };
    // matrixOf is a module function per caller.
  }, [ref, items, cues]);
  useFrame(({ gl }) => {
    const mesh = ref.current;
    if (!running.current || !mesh) return;
    const now = Date.now();
    let cued = false;
    items.forEach((item, index) => {
      const base = matrixOf(item);
      const matrix = cuedMatrix(item, base, cues, now);
      if (!matrix) return;
      mesh.setMatrixAt(index, matrix);
      cued = true;
    });
    const moving = cues.move !== null && moveProgress(cues.move.at, now) < 1;
    const growing = cues.arrival !== null && !arrivalDone(cues.arrival.at, now);
    if (!moving && !growing) running.current = false;
    if (!cued) {
      running.current = false;
      return;
    }
    mesh.instanceMatrix.needsUpdate = true;
    // Shadows are drawn on demand (`StaticShadows`), so they follow the items by hand.
    gl.shadowMap.needsUpdate = true;
  });
}

/** Writes each item's matrix and color into the instanced mesh, and tweens the cued ones. */
function useInstances(
  items: Placed[],
  matrixOf: MatrixOf = atState,
  cues: ItemCues = NO_CUES,
) {
  const ref = useRef<InstancedMesh>(null);
  useLayoutEffect(() => {
    const mesh = ref.current;
    if (!mesh) return;
    items.forEach((item, index) => {
      mesh.setMatrixAt(index, matrixOf(item));
      mesh.setColorAt(index, item.color);
    });
    mesh.instanceMatrix.needsUpdate = true;
    if (mesh.instanceColor) mesh.instanceColor.needsUpdate = true;
    mesh.computeBoundingSphere();
    // matrixOf is a module function per caller, so only the items change.
  }, [items]);
  useCueTween(ref, items, matrixOf, cues);
  return ref;
}

/** What a batch is drawn with: a primitive, or a loaded model's geometry and material. */
type BatchLook = { key: BatchKey; geometry: BufferGeometry; model?: StockModel };
function lookOf(key: BatchKey, models: StockModels): BatchLook {
  const model = models.get(key as StockModelId);
  return model ? { key, geometry: model.geometry, model } : { key, geometry: GEOMETRY[key as StockShape] };
}

type MeshProps = { look: BatchLook; items: Placed[]; cues: ItemCues };

function StockMesh({ look, items, cues }: MeshProps) {
  const ref = useInstances(items, atState, cues);

  // Products are instances, not objects, so a click is mapped back through the instance id.
  const onClick = (event: ThreeEvent<MouseEvent>) => {
    const placed =
      event.instanceId === undefined ? undefined : items[event.instanceId];
    if (!placed || isDrag(event)) return;
    event.stopPropagation();
    useUiStore.getState().select(placed.productId);
  };

  if (items.length === 0) return null;
  return (
    <instancedMesh
      ref={ref}
      args={[look.geometry, look.model?.material ?? STOCK_MATERIAL, items.length]}
      userData={{ stockItems: items }}
      onClick={onClick}
      castShadow
      receiveShadow
    />
  );
}

const glowMatrix = (item: Placed) =>
  new Matrix4().multiplyMatrices(item.matrix, SELECTED_SCALE);

/** The selected product's items again, glowing. Takes no pointer events and casts no shadow. */
function SelectedMesh({ look, items, cues }: MeshProps) {
  const ref = useInstances(items, glowMatrix, cues);
  if (items.length === 0) return null;
  return (
    <instancedMesh
      ref={ref}
      args={[look.geometry, selectedMaterialOf(look.model), items.length]}
      name={`stock-selected-${look.key}`}
    />
  );
}

const haloMatrix = (item: Placed) =>
  new Matrix4().multiplyMatrices(item.matrix, ANOMALY_SCALE);

/** Items of products with an open anomaly, inside their halo. Takes no pointer events and casts no shadow. */
function AnomalyMesh({
  look,
  severity,
  items,
  cues,
}: MeshProps & { severity: AnomalySeverity }) {
  const ref = useInstances(items, haloMatrix, cues);
  if (items.length === 0) return null;
  return (
    <instancedMesh
      ref={ref}
      args={[look.geometry, anomalyHaloMaterial(severity), items.length]}
      name={`stock-anomaly-${severity}-${look.key}`}
      renderOrder={1}
    />
  );
}

const OUTLINE_GEOMETRY = new EdgesGeometry(new BoxGeometry(1, 1, 1));

/** Which slot of a move a light is over. */
type SlotEnd = "from" | "to";

/**
 * The outline at a moved product's source and the lights over its slots, in the change
 * color. Made on first use, once the theme stylesheet has loaded; `showMarks` fades them.
 */
let ghostMaterial: LineBasicMaterial | null = null;
function moveGhostMaterial() {
  ghostMaterial ??= new LineBasicMaterial({
    color: changeColor(),
    transparent: true,
    opacity: MOVE_GHOST_OPACITY,
    depthWrite: false,
  });
  return ghostMaterial;
}
let ghostFillMaterial: MeshBasicMaterial | null = null;
function moveGhostFillMaterial() {
  ghostFillMaterial ??= new MeshBasicMaterial({
    color: changeColor(),
    transparent: true,
    opacity: MOVE_GHOST_FILL_OPACITY,
    depthWrite: false,
  });
  return ghostFillMaterial;
}
const slotMaterials = new Map<SlotEnd, MeshStandardMaterial>();
function moveSlotMaterial(end: SlotEnd) {
  let material = slotMaterials.get(end);
  if (!material) {
    material = new MeshStandardMaterial({
      color: changeColor(),
      emissive: changeColor(),
      emissiveIntensity: MOVE_SLOT_GLOW,
      transparent: true,
      opacity: MOVE_SLOT_OPACITY,
      depthWrite: false,
    });
    slotMaterials.set(end, material);
  }
  return material;
}

/** Sets how strongly the outline and both slot lights show; the destination also takes the arrival flash. */
function showMarks(levels: MarkLevels) {
  moveGhostMaterial().opacity = MOVE_GHOST_OPACITY * levels.ghost;
  moveGhostFillMaterial().opacity = MOVE_GHOST_FILL_OPACITY * levels.ghost;
  showArrows(levels.ghost);
  const from = moveSlotMaterial("from");
  from.opacity = MOVE_SLOT_OPACITY * levels.from;
  from.emissiveIntensity = MOVE_SLOT_GLOW * levels.from;
  const to = moveSlotMaterial("to");
  to.opacity = Math.min(1, MOVE_SLOT_OPACITY * (levels.to + levels.flash));
  to.emissiveIntensity = MOVE_SLOT_GLOW * (levels.to + levels.flash);
}

/**
 * A translucent ghost where each moved product stood: a faint box around the items it had
 * there, under a thin outline. Takes no pointer events and casts no shadow.
 */
function GhostOutlines({ matrices }: { matrices: Matrix4[] }) {
  const placements = useMemo(
    () =>
      matrices.map((matrix) => {
        const position = new Vector3();
        const quaternion = new Quaternion();
        const scale = new Vector3();
        matrix.decompose(position, quaternion, scale);
        return { position, quaternion, scale };
      }),
    [matrices],
  );
  return (
    <>
      {placements.map((placement, index) => (
        <group key={index} {...placement}>
          <lineSegments name="stock-ghost-outline" args={[OUTLINE_GEOMETRY, moveGhostMaterial()]} renderOrder={1} />
          <mesh
            name="stock-ghost-fill"
            geometry={GEOMETRY[STOCK_SHAPE.Box]}
            material={moveGhostFillMaterial()}
            raycast={NO_POINTER}
            renderOrder={1}
          />
        </group>
      ))}
    </>
  );
}

/** A light over the source or destination slot of each move. */
function SlotLights({ matrices, end }: { matrices: Matrix4[]; end: SlotEnd }) {
  const ref = useRef<InstancedMesh>(null);
  useLayoutEffect(() => {
    const mesh = ref.current;
    if (!mesh) return;
    matrices.forEach((matrix, index) => mesh.setMatrixAt(index, matrix));
    mesh.instanceMatrix.needsUpdate = true;
    mesh.computeBoundingSphere();
  }, [matrices]);
  if (matrices.length === 0) return null;
  return (
    <instancedMesh
      ref={ref}
      args={[GEOMETRY[STOCK_SHAPE.Box], moveSlotMaterial(end), matrices.length]}
      name={`stock-moved-slots-${end}`}
      renderOrder={1}
    />
  );
}

const NO_SLOTS: Matrix4[] = [];
const NO_ARROWS: QuadraticBezierCurve3[] = [];
/** Marks take no clicks: a click goes through to the item or fixture behind. */
const NO_POINTER = () => null;
const NO_ITEMS: Placed[] = [];

const keysOf = (batches: Batches) => Object.keys(batches) as BatchKey[];

/** The items of `batches` whose product passes `keep`, per shape or model. */
function pick(batches: Batches, keep: (productId: string) => boolean) {
  return Object.fromEntries(
    keysOf(batches).map((key) => [key, (batches[key] ?? []).filter((item) => keep(item.productId))]),
  ) as Batches;
}

/**
 * All products in the store as one instanced mesh per primitive shape. Click an item to
 * select its product. The selected product glows, and a product with an open anomaly
 * gets a halo; only products in the twin state are drawn, so a stale anomaly shows nothing.
 * The Simulation view shows no halos (`useShownAnomalies`).
 *
 * A recent move (`useRecentChanges`) carries the product's items on an arc from its source
 * slot to its destination, outlines where it stood, and lights both slots: the light hands
 * over from source to destination as the items travel, flashes when they land, and fades
 * out (`markLevels`, `marksShown`); in the Simulation view they hold a while before they fade.
 * A translucent ghost marks where it stood, with a line from
 * there to its destination. With reduced motion the items stand at the destination from the
 * start, and the ghost, line and lights hold still for as long as the change cue lasts.
 *
 * The items a recent change adds to a product (more facings, a shelf gain) grow in from
 * their shelf, one after another (`arrivalCueOf`); its slot glows meanwhile (`SlotMarksLayer`).
 * With reduced motion they are simply there.
 */
export function Stock({ store, models = NO_MODELS }: { store: StoreFixture; models?: StockModels }) {
  const batches = useMemo(() => buildStock(store, models), [store, models]);
  const gl = useThree((state) => state.gl);
  // Shadows are drawn on demand (`StaticShadows`): redraw them once the models replace the primitives.
  useEffect(() => {
    gl.shadowMap.needsUpdate = true;
  }, [gl, models]);
  const productId = useUiStore(selectedProductId);
  const anomalies = useShownAnomalies();
  const selected = useMemo(
    () => pick(batches, (id) => id === productId),
    [batches, productId],
  );
  const anomalous = useMemo(() => {
    const worst = worstSeverities(anomalies);
    return ANOMALY_SEVERITIES.map((severity) => ({
      severity,
      batches: pick(batches, (id) => worst.get(id) === severity),
    }));
  }, [batches, anomalies]);
  const motion = useMemo(() => !prefersReducedMotion(), []);
  const change = useRecentChanges();
  const move = useMemo(() => moveCueOf(store, change), [store, change]);
  const outlines = useMemo(
    () => (move ? ghostOutlines(move, Object.values(buildStock(move.ghost, models)).flat()) : NO_SLOTS),
    [move, models],
  );
  const arrival = useMemo(() => {
    const gained = gainedSkus(change);
    if (!change || gained.size === 0) return null;
    return arrivalCueOf(change, drawnCounts(buildStock(storeBefore(store, change, gained), models)), drawnCounts(batches));
  }, [store, change, models, batches]);
  const cues = useMemo<ItemCues>(() => (motion ? { move, arrival } : NO_CUES), [motion, move, arrival]);
  // The proposal is there to be looked at: in the Simulation view the marks stay a while.
  const hold = useUiStore((state) => state.viewMode) === VIEW_MODE.Simulation ? MOVE_MARK_HOLD_SIMULATION_MS : 0;
  const marks = useRef<Group>(null);
  useFrame(({ clock }) => {
    if (motion && anomalies.length) pulseHalos(Math.sin(clock.elapsedTime * Math.PI * 2 * ANOMALY_PULSE_HZ));
    const now = Date.now();
    const shown = move !== null && marksShown(move.at, now, motion, hold);
    if (marks.current) marks.current.visible = shown;
    if (shown) showMarks(motion ? markLevels(move.at, now, hold) : STEADY_MARKS);
  });

  return (
    <group name="stock">
      {keysOf(batches).map((key) => (
        <StockMesh key={key} look={lookOf(key, models)} items={batches[key] ?? NO_ITEMS} cues={cues} />
      ))}
      {keysOf(selected).map((key) => (
        <SelectedMesh
          key={`selected-${key}`}
          look={lookOf(key, models)}
          items={selected[key] ?? NO_ITEMS}
          cues={cues}
        />
      ))}
      {anomalous.flatMap(({ severity, batches: items }) =>
        keysOf(items).map((key) => (
          <AnomalyMesh
            key={`anomaly-${severity}-${key}`}
            look={lookOf(key, models)}
            severity={severity}
            items={items[key] ?? NO_ITEMS}
            cues={cues}
          />
        )),
      )}
      <group ref={marks} name="stock-move-marks">
        <GhostOutlines matrices={outlines} />
        <SlotLights matrices={move?.fromSlots ?? NO_SLOTS} end="from" />
        <SlotLights matrices={move?.toSlots ?? NO_SLOTS} end="to" />
        <MoveArrows curves={move?.arrows ?? NO_ARROWS} />
      </group>
    </group>
  );
}
