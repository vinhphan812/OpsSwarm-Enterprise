import { GLASS_DOOR_COOLER } from "@/constants/dimensions.constant";
import { STOCK_KIND } from "@/enums/scene.enum";
import type { StockSurface } from "@/types/scene.type";
import { Parts, partBuilder } from "./parts";

const { width: W, height: H, depth: D } = GLASS_DOOR_COOLER;
const SIDE = 0.05;
const PLINTH = 0.12;
const HEADER = 0.26;
const DOOR_BOTTOM = PLINTH + 0.01;
const DOOR_TOP = H - HEADER;
const DOOR_H = DOOR_TOP - DOOR_BOTTOM;
const DOOR_W = (W - 2 * SIDE) / 2;
const STILE = 0.04;

/** Two-door upright cooler with a lit interior and a backlit header. Front at +Z. */
const PARTS = (() => {
  const { parts, add } = partBuilder();
  const inner = W - 2 * SIDE;
  const zFront = D / 2;

  for (const side of [-1, 1]) {
    add("cabinet", [side * (W / 2 - SIDE / 2), H / 2, 0], [SIDE, H, D]);
    // LED strip down each inside corner of the cabinet.
    add("light", [side * (inner / 2 - 0.01), (DOOR_BOTTOM + DOOR_TOP) / 2, zFront - 0.06], [0.015, DOOR_H, 0.015]);
    add("interior", [side * (inner / 2 - 0.004), (DOOR_BOTTOM + DOOR_TOP) / 2, -0.02], [0.008, DOOR_H, D - 0.1]);
  }
  add("cabinet", [0, H - 0.03, 0], [W, 0.06, D]);
  add("cabinetDark", [0, PLINTH / 2, 0], [W, PLINTH, D]);
  add("cabinet", [0, H / 2, -D / 2 + 0.02], [W, H, 0.04]);
  add("interior", [0, (DOOR_BOTTOM + DOOR_TOP) / 2, -D / 2 + 0.045], [inner, DOOR_H, 0.01]);

  // Header: frame with a backlit sign panel.
  add("cabinet", [0, H - HEADER / 2, zFront - 0.02], [inner, HEADER, 0.04]);
  add("light", [0, H - HEADER / 2 - 0.01, zFront + 0.001], [inner - 0.08, HEADER - 0.09, 0.004]);

  for (const y of GLASS_DOOR_COOLER.shelves) {
    add("rack", [0, y, -0.03], [inner - 0.02, 0.02, D - 0.16]);
    add("rack", [0, y - 0.015, D / 2 - 0.115], [inner - 0.02, 0.03, 0.01]);
  }

  for (const side of [-1, 1]) {
    const cx = side * (DOOR_W / 2);
    const z = zFront - STILE / 2;
    const yMid = DOOR_BOTTOM + DOOR_H / 2;
    add("steel", [cx - DOOR_W / 2 + STILE / 2, yMid, z], [STILE, DOOR_H, STILE]);
    add("steel", [cx + DOOR_W / 2 - STILE / 2, yMid, z], [STILE, DOOR_H, STILE]);
    add("steel", [cx, DOOR_BOTTOM + STILE / 2, z], [DOOR_W, STILE, STILE]);
    add("steel", [cx, DOOR_TOP - STILE / 2, z], [DOOR_W, STILE, STILE]);
    add("glass", [cx, yMid, z], [DOOR_W - 2 * STILE, DOOR_H - 2 * STILE, 0.008]);
    // Pull handles on the meeting stiles.
    add("steel", [side * 0.06, yMid, zFront + 0.025], [0.022, 0.42, 0.022]);
    for (const dy of [-0.19, 0.19]) add("steel", [side * 0.06, yMid + dy, zFront + 0.01], [0.02, 0.02, 0.03]);
  }
  return parts;
})();

/** Cabinet floor and every shelf, behind the doors. */
export const GLASS_DOOR_COOLER_SURFACES: StockSurface[] = (() => {
  const tops = [PLINTH, ...GLASS_DOOR_COOLER.shelves.map((y) => y + 0.01)];
  return tops.map((top, i): StockSurface => ({
    kind: STOCK_KIND.Fresh,
    center: [0, top, -0.03],
    width: W - 2 * SIDE - 0.04,
    depth: D - 0.2,
    maxHeight: (tops[i + 1] ?? DOOR_TOP - 0.02) - top - 0.03,
    slots: 2,
  }));
})();

export function GlassDoorCooler() {
  return <Parts parts={PARTS} />;
}
