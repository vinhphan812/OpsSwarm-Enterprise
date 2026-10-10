import { useRef } from "react";
import { MeshStandardMaterial, type Group } from "three";
import { SHELF, SHELF_SIDE_Z } from "@/constants/dimensions.constant";
import { ENTITY_TYPE, STOCK_KIND } from "@/enums/scene.enum";
import { entityProps } from "./entity";
import { useHover } from "@/hooks/hover.hook";
import { useSelectOnClick } from "@/hooks/selectEntity.hook";
import { useSelectionGlow } from "@/hooks/selectionGlow.hook";
import { isSelected, useUiStore } from "@/state/ui.store";
import { HitBox } from "./HitBox";
import { Boxes, Parts, partBuilder, type BoxSpec } from "./equipment/parts";
import { SlotProducts } from "./SlotProducts";
import type { ProductFixture, ShelfFixture, StockSurface } from "@/types/scene.type";
import { toTuple } from "@/scene/utils/transform";

const { width: W, sideDepth: D, height: H, bays: BAYS, post: P, board: B } = SHELF;

/** Upright x positions: one at each end and one between each pair of bays. */
const UPRIGHT_X = Array.from({ length: BAYS + 1 }, (_, i) => -W / 2 + P / 2 + (i * (W - P)) / BAYS);
const BAY_INNER = (W - P) / BAYS - P;
const BAY_CENTER_X = UPRIGHT_X.slice(0, -1).map((x, i) => (x + UPRIGHT_X[i + 1]) / 2);

const BEAM_H = 0.035;
const FENCE_HEIGHT = 0.06;
const ROD = 0.012;
/** Distance of the back-stop rod from the side's center, toward the back edge. */
const FENCE_Z = D / 2 - 0.02;

/** One shelving side: frame, boards, and fences, front at +Z. Built once and shared. */
const SHELF_PARTS = (() => {
  const { parts, add } = partBuilder();
  const zFront = D / 2 - P / 2;
  for (const x of UPRIGHT_X) {
    for (const z of [-zFront, zFront]) {
      add("frame", [x, H / 2, z], [P, H, P]);
      add("frame", [x, 0.005, z], [P * 1.8, 0.01, P * 1.8]);
    }
    // Side ties between the front and back upright.
    for (const y of [0.05, H - 0.02]) add("frame", [x, y, 0], [P * 0.7, P * 0.7, D - P]);
  }
  for (const top of SHELF.deckTops) {
    const beamY = top - B - BEAM_H / 2;
    for (const x of BAY_CENTER_X) {
      add("frame", [x, beamY, zFront], [BAY_INNER, BEAM_H, P * 0.7]);
      add("frame", [x, beamY, -zFront], [BAY_INNER, BEAM_H, P * 0.7]);
      add("wood", [x, top - B / 2, 0], [BAY_INNER - 0.01, B, D - 0.01]);
      // Back-stop rod on clips along the back edge, so stock cannot slide off the back;
      // the front stays open for picking.
      add("frame", [x, top + FENCE_HEIGHT, -FENCE_Z], [BAY_INNER - 0.02, ROD, ROD]);
      for (const dx of [-0.3, 0.3]) {
        add("steel", [x + dx * BAY_INNER, top + FENCE_HEIGHT / 2, -FENCE_Z], [ROD, FENCE_HEIGHT, ROD]);
      }
    }
  }
  return parts;
})();

/** Price strips on the front beams, drawn in the shelf's category color. */
const PRICE_STRIPS: BoxSpec[] = SHELF.deckTops.flatMap((top) =>
  BAY_CENTER_X.map((x) => ({
    p: [x, top - B - BEAM_H / 2, D / 2 + 0.002],
    s: [BAY_INNER, BEAM_H * 0.9, 0.004],
  })),
);

/** Strip material per category color. Module singletons shared by every shelf, so never disposed. */
const stripMaterials = new Map<string, MeshStandardMaterial>();

function stripMaterial(color: string): MeshStandardMaterial {
  let material = stripMaterials.get(color);
  if (!material) {
    material = new MeshStandardMaterial({ color, roughness: 0.5 });
    stripMaterials.set(color, material);
  }
  return material;
}

type ShelfProps = {
  shelf: ShelfFixture;
  products: ProductFixture[];
  /** Takes the pointer: hover and click-to-select. Off in tests, which have no pointer. */
  interactive?: boolean;
};

/** Both sides, back to back. The far side is the same run turned around. */
const SIDES = [
  { z: SHELF_SIDE_Z, rotationY: 0 },
  { z: -SHELF_SIDE_Z, rotationY: Math.PI },
] as const;

/** Clear height above the top deck, which has no deck over it. */
const TOP_DECK_CLEARANCE = 0.26;

/** Stock reaches this close to the board's open front edge. */
const STOCK_FRONT_GAP = 0.01;
/** Stock stays this far in front of the back edge, clear of the back-stop rod and its clips. */
const STOCK_BACK_GAP = 0.03;
/** Usable board depth for stock, between the two gaps. */
const STOCK_DEPTH = D - STOCK_FRONT_GAP - STOCK_BACK_GAP;
/** Center of the stock area from the side's center, toward the front. */
const STOCK_CENTER_Z = (STOCK_BACK_GAP - STOCK_FRONT_GAP) / 2;

/** Every bay of every deck on both sides, two product slots per bay. */
export const SHELF_SURFACES: StockSurface[] = SIDES.flatMap((side) =>
  SHELF.deckTops.flatMap((top, i) => {
    const next = SHELF.deckTops[i + 1];
    const maxHeight = next === undefined ? TOP_DECK_CLEARANCE : next - top - B - BEAM_H - 0.01;
    return BAY_CENTER_X.map(
      (x): StockSurface => ({
        kind: STOCK_KIND.Packaged,
        // The far side is turned around, so its bays run the other way and its front is -Z.
        center: [side.rotationY === 0 ? x : -x, top, side.z + (side.rotationY === 0 ? 1 : -1) * STOCK_CENTER_Z],
        width: BAY_INNER - 0.02,
        depth: STOCK_DEPTH,
        maxHeight,
        rotationY: side.rotationY,
        slots: 2,
      }),
    );
  }),
);

/** One double-sided gondola entity. A click selects it and lights it up. */
export function Shelf({ shelf, products, interactive = true }: ShelfProps) {
  const [, hoverHandlers] = useHover();
  const ref = useRef<Group>(null);
  const selected = useUiStore((state) => isSelected(state, shelf.shelfId, ENTITY_TYPE.Shelf));
  useSelectionGlow(ref, selected);
  const onClick = useSelectOnClick(shelf.shelfId, ENTITY_TYPE.Shelf);

  return (
    <group
      ref={ref}
      position={toTuple(shelf.position)}
      rotation={[0, shelf.rotationY, 0]}
      {...entityProps(shelf.shelfId, ENTITY_TYPE.Shelf)}
    >
      {SIDES.map((side) => (
        <group key={side.z} position={[0, 0, side.z]} rotation={[0, side.rotationY, 0]}>
          <Parts parts={SHELF_PARTS} />
          <Boxes boxes={PRICE_STRIPS} material={stripMaterial(shelf.color)} castShadow={false} />
        </group>
      ))}
      {interactive ? <HitBox size={[W, H, SHELF.depth]} handlers={hoverHandlers} onClick={onClick} /> : null}
      <SlotProducts slots={shelf.slots} products={products} />
    </group>
  );
}
