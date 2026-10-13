import type { Intersection } from "three";
import { useFrame, type ThreeEvent } from "@react-three/fiber";
import { useLayoutEffect, useMemo, useRef } from "react";
import {
  BoxGeometry,
  Color,
  CylinderGeometry,
  EdgesGeometry,
  IcosahedronGeometry,
  LineBasicMaterial,
  Matrix4,
  MeshStandardMaterial,
  Quaternion,
  Vector3,
  type BufferGeometry,
  type Group,
  type InstancedMesh,
} from "three";
import { selectedProductId, useUiStore } from "@/state/ui.store";
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
  MOVE_GHOST_OPACITY,
  MOVE_SLOT_GLOW,
  MOVE_SLOT_OPACITY,
  SELECTION_ITEM_GLOW,
} from "@/constants/scene.constant";
import { anomalyColor, changeColor, selectionColor } from "@/core/utils/theme";
import { ENTITY_TYPE, STOCK_KIND } from "@/enums/scene.enum";
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
  idFraction,
  productLook,
  stockItemFor,
  type StockItem,
} from "./catalog";
import { FACING_GAP, slotCapacity } from "./capacity";
import { surfaceMatrix, surfacesOf } from "./surfaces";

const GEOMETRY: Record<StockShape, BufferGeometry> = {
  [STOCK_SHAPE.Box]: new BoxGeometry(1, 1, 1),
  [STOCK_SHAPE.Cylinder]: new CylinderGeometry(0.5, 0.5, 1, 10),
  [STOCK_SHAPE.Sphere]: new IcosahedronGeometry(0.5, 1),
};
const SHAPES = Object.keys(GEOMETRY) as StockShape[];

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

const ROW_GAP = 0.005;
/** Items are drawn a little under their footprint, so neighbours show a seam between them. */
const ITEM_INSET = 0.92;
/** Brightness spread between items of one product, so a facing does not read as flat plastic. */
const SHADE_SPREAD = 0.12;

/** One drawn item. `holderId` is the shelf or equipment it stands on. */
type Placed = {
  matrix: Matrix4;
  color: Color;
  productId: string;
  holderId: string;
};
type Batches = Record<StockShape, Placed[]>;

/** Takes an item position in the surface's own frame. */
type Emit = (position: Tuple3) => void;

/**
 * The item at its natural width, no taller than the surface's clear height. Fruit
 * shrinks evenly so it stays round. Facings past the slot's capacity are not drawn
 * (`slotCapacity`), so items never run past the slot's edges.
 */
export function fitItem(item: StockItem, surface: StockSurface): StockItem {
  const [w, h, d] = item.size;
  if (item.shape === STOCK_SHAPE.Sphere) {
    const scale = Math.min(1, surface.maxHeight / h);
    return { ...item, size: [w * scale, h * scale, d * scale] };
  }
  return { ...item, size: [w, Math.min(h, surface.maxHeight), d] };
}

/**
 * Packaged goods: the facings side by side, rows behind them, stacked when the item
 * stacks. Emitted front row first, so a short stock empties the shelf from the back.
 */
function layFacings(
  surface: StockSurface,
  slot: SlotFixture,
  item: StockItem,
  facings: number,
  emit: Emit,
) {
  const [w, h, d] = item.size;
  const total = facings * (w + FACING_GAP) - FACING_GAP;
  const rows = Math.max(1, Math.floor(surface.depth / (d + ROW_GAP)));
  const layers = item.stacks
    ? Math.max(1, Math.min(3, Math.floor(surface.maxHeight / h)))
    : 1;
  for (let row = 0; row < rows; row += 1) {
    const z = surface.depth / 2 - d / 2 - row * (d + ROW_GAP);
    for (let layer = 0; layer < layers; layer += 1) {
      for (let f = 0; f < facings; f += 1) {
        const x = slot.offset - total / 2 + w / 2 + f * (w + FACING_GAP);
        emit([x, layer * h + h / 2, z]);
      }
    }
  }
}

/**
 * Loose fruit: `facings` columns across the slot, a full bottom layer and a smaller
 * heap on top. Emitted bottom layer first, so a short stock loses the heap first.
 */
function layHeap(
  surface: StockSurface,
  slot: SlotFixture,
  item: StockItem,
  facings: number,
  emit: Emit,
) {
  const [w, h, d] = item.size;
  const back = Math.max(1, Math.floor(surface.depth / d));
  const layers = Math.max(
    1,
    Math.min(3, Math.floor(surface.maxHeight / (h * 0.85))),
  );
  const left = slot.offset - (facings * w) / 2;
  for (let layer = 0; layer < layers; layer += 1) {
    // Each layer sits in the hollows of the one below and shrinks toward the middle.
    for (let i = layer; i < facings - layer; i += 1) {
      for (let j = layer; j < back - layer; j += 1) {
        const x = left + (i + 0.5 + layer * 0.5) * w;
        const z = -surface.depth / 2 + (j + 0.5 + layer * 0.5) * d;
        if (Math.abs(z) > surface.depth / 2 - d / 2) continue;
        emit([x, h / 2 + layer * h * 0.8, z]);
      }
    }
  }
}

type Holder = {
  matrix: Matrix4;
  surfaces: StockSurface[];
  slots: Map<string, SlotFixture>;
};

/**
 * Every product drawn at its slot with its facings, one item per unit of shelf
 * stock up to what the facings hold. Facings past the slot's capacity are not drawn. Nothing is drawn for zero facings or zero
 * stock. A product whose shelf or slot is unknown is skipped; `toSceneStore`
 * reports those before they get here.
 */
export function buildStock(store: StoreFixture): Batches {
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
    // Never more than the slot holds; `toSceneStore` reports the overflow.
    const facings = Math.min(Math.max(0, product.facings), slotCapacity(slot, natural));
    const item = fitItem(natural, surface);
    const look = productLook(item, product.productId);
    const base = new Color(look.color);
    const [w, h, d] = item.size;
    const height = h * look.height;
    const inset = item.shape === STOCK_SHAPE.Sphere ? 1 : ITEM_INSET;
    let index = 0;
    const toWorld = new Matrix4().multiplyMatrices(
      holder.matrix,
      surfaceMatrix(surface),
    );
    let stock = product.shelfQuantity;
    const emit: Emit = ([x, y, z]) => {
      if (stock <= 0) return;
      stock -= 1;
      index += 1;
      // Scaling y with the height keeps a shorter product standing on its surface and its stack.
      scratch.local.compose(
        scratch.pos.set(x, y * look.height, z),
        scratch.quat.identity(),
        scratch.scale.set(w * inset, height, d * inset),
      );
      const shade =
        1 + (idFraction(product.productId, index + 1) - 0.5) * SHADE_SPREAD;
      batches[item.shape].push({
        matrix: new Matrix4().multiplyMatrices(toWorld, scratch.local),
        color: base.clone().multiplyScalar(shade),
        productId: product.productId,
        holderId: product.shelfId,
      });
    };
    if (surface.kind === STOCK_KIND.Fruit) {
      layHeap(surface, slot, item, facings, emit);
    } else {
      layFacings(surface, slot, item, facings, emit);
    }
  }
  return batches;
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

/**
 * Carries the moved products' items from their source slot to where the state puts them
 * over `MOVE_TWEEN_MS`, from when the move appeared. The layout effect has already drawn
 * them at the state; each frame of the tween draws them on the way there, and its last
 * frame draws the state again. A tween cut short (a newer state, another view) is put
 * back at the state too, so the scene never stays between two slots.
 */
function useMoveTween(
  ref: { current: InstancedMesh | null },
  items: Placed[],
  matrixOf: MatrixOf,
  tween: MoveCue | null,
) {
  const running = useRef(false);
  useLayoutEffect(() => {
    running.current = tween !== null;
    return () => {
      const mesh = ref.current;
      if (!running.current || !mesh) return;
      running.current = false;
      items.forEach((item, index) => mesh.setMatrixAt(index, matrixOf(item)));
      mesh.instanceMatrix.needsUpdate = true;
    };
    // matrixOf is a module function per caller.
  }, [ref, items, tween]);
  useFrame(({ gl }) => {
    const mesh = ref.current;
    if (!running.current || !tween || !mesh) return;
    const progress = moveProgress(tween.at, Date.now());
    let moved = false;
    items.forEach((item, index) => {
      const offset = tween.offsets.get(item.productId);
      if (!offset) return;
      mesh.setMatrixAt(index, tweenMatrix(matrixOf(item), offset, progress, tweened));
      moved = true;
    });
    if (progress >= 1 || !moved) running.current = false;
    if (!moved) return;
    mesh.instanceMatrix.needsUpdate = true;
    // Shadows are drawn on demand (`StaticShadows`), so they follow the items by hand.
    gl.shadowMap.needsUpdate = true;
  });
}

/** Writes each item's matrix and color into the instanced mesh, and tweens the moved ones. */
function useInstances(
  items: Placed[],
  matrixOf: MatrixOf = atState,
  tween: MoveCue | null = null,
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
  useMoveTween(ref, items, matrixOf, tween);
  return ref;
}

type MeshProps = { shape: StockShape; items: Placed[]; tween: MoveCue | null };

function StockMesh({ shape, items, tween }: MeshProps) {
  const ref = useInstances(items, atState, tween);

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
      args={[GEOMETRY[shape], STOCK_MATERIAL, items.length]}
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
function SelectedMesh({ shape, items, tween }: MeshProps) {
  const ref = useInstances(items, glowMatrix, tween);
  if (items.length === 0) return null;
  return (
    <instancedMesh
      ref={ref}
      args={[GEOMETRY[shape], selectedItemMaterial(), items.length]}
      name={`stock-selected-${shape}`}
    />
  );
}

const haloMatrix = (item: Placed) =>
  new Matrix4().multiplyMatrices(item.matrix, ANOMALY_SCALE);

/** Items of products with an open anomaly, inside their halo. Takes no pointer events and casts no shadow. */
function AnomalyMesh({
  shape,
  severity,
  items,
  tween,
}: MeshProps & { severity: AnomalySeverity }) {
  const ref = useInstances(items, haloMatrix, tween);
  if (items.length === 0) return null;
  return (
    <instancedMesh
      ref={ref}
      args={[GEOMETRY[shape], anomalyHaloMaterial(severity), items.length]}
      name={`stock-anomaly-${severity}-${shape}`}
      renderOrder={1}
    />
  );
}

/** A thin outline where each moved product stood. Takes no pointer events and casts no shadow. */
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
        <lineSegments
          key={index}
          name="stock-ghost-outline"
          args={[OUTLINE_GEOMETRY, moveGhostMaterial()]}
          {...placement}
          renderOrder={1}
        />
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

/** The items of `batches` whose product passes `keep`, per shape. */
function pick(batches: Batches, keep: (productId: string) => boolean) {
  return Object.fromEntries(
    SHAPES.map((shape) => [shape, batches[shape].filter((item) => keep(item.productId))]),
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
 * out (`markLevels`, `marksShown`). With reduced motion the items stand at the destination
 * from the start, and the outline and lights hold still for as long as the tween would take.
 */
export function Stock({ store }: { store: StoreFixture }) {
  const batches = useMemo(() => buildStock(store), [store]);
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
    () => (move ? ghostOutlines(move, Object.values(buildStock(move.ghost)).flat()) : NO_SLOTS),
    [move],
  );
  const tween = motion ? move : null;
  const marks = useRef<Group>(null);
  useFrame(({ clock }) => {
    if (motion && anomalies.length) pulseHalos(Math.sin(clock.elapsedTime * Math.PI * 2 * ANOMALY_PULSE_HZ));
    const now = Date.now();
    const shown = move !== null && marksShown(move.at, now, motion);
    if (marks.current) marks.current.visible = shown;
    if (shown) showMarks(motion ? markLevels(move.at, now) : STEADY_MARKS);
  });

  return (
    <group name="stock">
      {SHAPES.map((shape) => (
        <StockMesh key={shape} shape={shape} items={batches[shape]} tween={tween} />
      ))}
      {SHAPES.map((shape) => (
        <SelectedMesh
          key={`selected-${shape}`}
          shape={shape}
          items={selected[shape]}
          tween={tween}
        />
      ))}
      {anomalous.flatMap(({ severity, batches: items }) =>
        SHAPES.map((shape) => (
          <AnomalyMesh
            key={`anomaly-${severity}-${shape}`}
            shape={shape}
            severity={severity}
            items={items[shape]}
            tween={tween}
          />
        )),
      )}
      <group ref={marks} name="stock-move-marks">
        <GhostOutlines matrices={outlines} />
        <SlotLights matrices={move?.fromSlots ?? NO_SLOTS} end="from" />
        <SlotLights matrices={move?.toSlots ?? NO_SLOTS} end="to" />
      </group>
    </group>
  );
}
