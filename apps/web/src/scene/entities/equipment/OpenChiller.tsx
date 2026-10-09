import { OPEN_CHILLER } from "@/constants/dimensions.constant";
import { STOCK_KIND } from "@/enums/scene.enum";
import type { StockSurface, Tuple3 } from "@/types/scene.type";
import { tiltX } from "@/scene/utils/transform";
import { Parts, partBuilder } from "./parts";

const { width: W, height: H, depth: D } = OPEN_CHILLER;
const SIDE = 0.06;
const CANOPY_H = 0.22;
const CANOPY_D = 0.3;
const WELL_TOP = 0.36;
const SHELF_TILT = 0.12;

const Z_BACK = -D / 2 + 0.06;

/** Shelves get shallower toward the top so the lower ones stay visible. */
function shelfSpan(i: number) {
  const depth = 0.6 - (0.16 * i) / (OPEN_CHILLER.shelves.length - 1);
  return { depth, z: Z_BACK + depth / 2 };
}

/** Open-front multideck chiller: canopy, tilted shelves, and a deep base well. Front at +Z. */
const PARTS = (() => {
  const { parts, add } = partBuilder();
  const inner = W - 2 * SIDE;
  const zFront = D / 2;
  const zBack = Z_BACK;

  for (const side of [-1, 1]) {
    const x = side * (W / 2 - SIDE / 2);
    add("cabinet", [x, H / 2, 0], [SIDE, H, D]);
    // Bright trim down the front edge of each end panel.
    add("steel", [x, (H - CANOPY_H) / 2 + 0.15, zFront + 0.006], [SIDE + 0.004, H - CANOPY_H - 0.3, 0.012]);
    add("interior", [side * (inner / 2 - 0.004), H / 2 + 0.1, -0.05], [0.008, H - 0.6, D - 0.2]);
  }
  add("cabinet", [0, H / 2, -D / 2 + 0.03], [W, H, 0.06]);
  add("interior", [0, H / 2 + 0.1, zBack + 0.005], [inner, H - 0.6, 0.01]);
  add("cabinet", [0, H - 0.02, 0], [W, 0.04, D]);

  // Canopy with two down-lights at the ends.
  add("cabinetDark", [0, H - CANOPY_H / 2, zFront - CANOPY_D / 2], [inner, CANOPY_H, CANOPY_D]);
  for (const side of [-1, 1]) {
    add("light", [side * (inner / 2 - 0.14), H - 0.06, zFront + 0.002], [0.14, 0.025, 0.004]);
  }
  add("light", [0, H - CANOPY_H - 0.003, zFront - CANOPY_D / 2], [inner - 0.1, 0.006, 0.05]);

  // Base: kick panel, front sill, and the well floor.
  add("cabinetDark", [0, 0.12, zFront - 0.04], [W, 0.24, 0.08]);
  add("cabinet", [0, WELL_TOP / 2, 0], [inner, WELL_TOP - 0.02, D - 0.12]);
  add("rack", [0, WELL_TOP, 0], [inner, 0.02, D - 0.12]);
  add("steel", [0, WELL_TOP + 0.04, zFront - 0.03], [inner, 0.08, 0.02]);

  OPEN_CHILLER.shelves.forEach((y, i) => {
    const { depth, z } = shelfSpan(i);
    const pivot: Tuple3 = [0, y, z];
    add("rack", [0, y, z], [inner - 0.02, 0.02, depth], [SHELF_TILT, 0, 0]);
    add("cabinetDark", tiltX([0, y + 0.01, z + depth / 2], SHELF_TILT, pivot), [inner - 0.02, 0.04, 0.012], [
      SHELF_TILT,
      0,
      0,
    ]);
  });
  return parts;
})();

/** The base well and every tilted shelf. */
export const OPEN_CHILLER_SURFACES: StockSurface[] = [
  {
    kind: STOCK_KIND.Frozen,
    center: [0, WELL_TOP + 0.01, 0],
    width: W - 2 * SIDE - 0.04,
    depth: D - 0.2,
    maxHeight: 0.14,
    slots: 2,
  },
  ...OPEN_CHILLER.shelves.map((y, i, all): StockSurface => {
    const { depth, z } = shelfSpan(i);
    return {
      kind: STOCK_KIND.Frozen,
      center: [0, y + 0.01, z],
      width: W - 2 * SIDE - 0.04,
      depth: depth - 0.04,
      maxHeight: (all[i + 1] ?? H - CANOPY_H + 0.06) - y - 0.05,
      tilt: SHELF_TILT,
      slots: 2,
    };
  }),
];

export function OpenChiller() {
  return <Parts parts={PARTS} />;
}
