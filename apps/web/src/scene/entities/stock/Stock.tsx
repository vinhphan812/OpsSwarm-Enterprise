import type { ThreeEvent } from "@react-three/fiber";
import { useLayoutEffect, useMemo, useRef } from "react";
import {
  BoxGeometry,
  Color,
  CylinderGeometry,
  IcosahedronGeometry,
  Matrix4,
  MeshStandardMaterial,
  Quaternion,
  Vector3,
  type BufferGeometry,
  type InstancedMesh,
} from "three";
import { useUiStore } from "@/state/ui.store";
import { ENTITY_TYPE, STOCK_KIND } from "@/enums/scene.enum";
import type { SlotFixture, StoreFixture } from "@/scene/types";
import { entityMatrix, type Tuple3 } from "@/scene/utils/transform";
import { STOCK_SHAPE, type StockShape } from "@/enums/stock.enum";
import { stockItemFor, type StockItem } from "./catalog";
import type { StockSurface } from "./surface";
import { surfaceMatrix, surfacesOf } from "./surfaces";

const GEOMETRY: Record<StockShape, BufferGeometry> = {
  [STOCK_SHAPE.Box]: new BoxGeometry(1, 1, 1),
  [STOCK_SHAPE.Cylinder]: new CylinderGeometry(0.5, 0.5, 1, 10),
  [STOCK_SHAPE.Sphere]: new IcosahedronGeometry(0.5, 1),
};
const SHAPES = Object.keys(GEOMETRY) as StockShape[];

/** White base; each instance carries its own color. */
const STOCK_MATERIAL = new MeshStandardMaterial({ color: "#ffffff", roughness: 0.6 });

const FACING_GAP = 0.008;
const ROW_GAP = 0.005;

type Placed = { matrix: Matrix4; color: Color; productId: string };
type Batches = Record<StockShape, Placed[]>;

/** Takes an item position in the surface's own frame. */
type Emit = (position: Tuple3) => void;

/**
 * Packaged goods: the facings side by side, rows behind them, stacked when the item
 * stacks. Emitted front row first, so a short stock empties the shelf from the back.
 */
function layFacings(surface: StockSurface, slot: SlotFixture, item: StockItem, facings: number, emit: Emit) {
  const [w, h, d] = item.size;
  const total = facings * (w + FACING_GAP) - FACING_GAP;
  const rows = Math.max(1, Math.floor(surface.depth / (d + ROW_GAP)));
  const layers = item.stacks ? Math.max(1, Math.min(3, Math.floor(surface.maxHeight / h))) : 1;
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
function layHeap(surface: StockSurface, slot: SlotFixture, item: StockItem, facings: number, emit: Emit) {
  const [w, h, d] = item.size;
  const back = Math.max(1, Math.floor(surface.depth / d));
  const layers = Math.max(1, Math.min(3, Math.floor(surface.maxHeight / (h * 0.85))));
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

type Holder = { matrix: Matrix4; surfaces: StockSurface[]; slots: Map<string, SlotFixture> };

/**
 * Every product drawn at its slot with its facings, one item per unit of shelf
 * stock up to what the facings hold. Nothing is drawn for zero facings or zero
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

    const item = stockItemFor(surface.kind);
    const color = new Color(item.color);
    const toWorld = new Matrix4().multiplyMatrices(holder.matrix, surfaceMatrix(surface));
    let stock = product.shelfQuantity;
    const emit: Emit = ([x, y, z]) => {
      if (stock <= 0) return;
      stock -= 1;
      scratch.local.compose(
        scratch.pos.set(x, y, z),
        scratch.quat.identity(),
        scratch.scale.set(...item.size),
      );
      batches[item.shape].push({
        matrix: new Matrix4().multiplyMatrices(toWorld, scratch.local),
        color,
        productId: product.productId,
      });
    };
    const facings = Math.max(0, product.facings);
    if (surface.kind === STOCK_KIND.Fruit) {
      layHeap(surface, slot, item, facings, emit);
    } else {
      layFacings(surface, slot, item, facings, emit);
    }
  }
  return batches;
}

function StockMesh({ shape, items }: { shape: StockShape; items: Placed[] }) {
  const ref = useRef<InstancedMesh>(null);

  // Products are instances, not objects, so a click is mapped back through the instance id.
  const onClick = (event: ThreeEvent<MouseEvent>) => {
    const placed = event.instanceId === undefined ? undefined : items[event.instanceId];
    if (!placed) return;
    event.stopPropagation();
    useUiStore.getState().select(placed.productId);
  };

  useLayoutEffect(() => {
    const mesh = ref.current;
    if (!mesh) return;
    items.forEach((item, index) => {
      mesh.setMatrixAt(index, item.matrix);
      mesh.setColorAt(index, item.color);
    });
    mesh.instanceMatrix.needsUpdate = true;
    if (mesh.instanceColor) mesh.instanceColor.needsUpdate = true;
    mesh.computeBoundingSphere();
  }, [items]);

  if (items.length === 0) return null;
  return (
    <instancedMesh
      ref={ref}
      args={[GEOMETRY[shape], STOCK_MATERIAL, items.length]}
      onClick={onClick}
      castShadow
      receiveShadow
    />
  );
}

/** All products in the store as one instanced mesh per primitive shape. Click an item to select its product. */
export function Stock({ store }: { store: StoreFixture }) {
  const batches = useMemo(() => buildStock(store), [store]);

  return (
    <group name="stock">
      {SHAPES.map((shape) => (
        <StockMesh key={shape} shape={shape} items={batches[shape]} />
      ))}
    </group>
  );
}
