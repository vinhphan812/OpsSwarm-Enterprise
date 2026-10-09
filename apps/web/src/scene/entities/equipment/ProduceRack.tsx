import { PRODUCE_RACK } from "@/constants/dimensions.constant";
import { STOCK_KIND } from "@/enums/scene.enum";
import type { StockSurface, Tuple3 } from "@/types/scene.type";
import { tiltX } from "@/scene/utils/transform";
import { Parts, partBuilder } from "./parts";

const { bays: BAYS, bayWidth: BW, depth: D, frontHeight: FH, backHeight: BH, tilt: TILT } = PRODUCE_RACK;
const W = BAYS * BW;
const TUBE = 0.035;
const TRAY_DEPTH = D - 0.06;
const TRAY_WALL = 0.012;
const TRAY_LIP = 0.12;

/** Leaning side frames with wooden trays tilted toward the shopper. Front at +Z. */
const PARTS = (() => {
  const { parts, add } = partBuilder();
  const zEdge = D / 2 - TUBE / 2;

  for (let i = 0; i <= BAYS; i += 1) {
    const x = -W / 2 + i * BW;
    add("frame", [x, FH / 2, zEdge], [TUBE, FH, TUBE]);
    add("frame", [x, BH / 2, -zEdge], [TUBE, BH, TUBE]);
    add("frame", [x, 0.03, 0], [TUBE, TUBE, D]);
    // Sloped top bar from the low front upright to the tall back one.
    const rise = BH - FH;
    const run = D - TUBE;
    add("frame", [x, (FH + BH) / 2, 0], [TUBE, TUBE, Math.hypot(rise, run)], [Math.atan2(rise, run), 0, 0]);
  }

  for (const top of PRODUCE_RACK.trayTops) {
    for (let i = 0; i < BAYS; i += 1) {
      const x = -W / 2 + (i + 0.5) * BW;
      const w = BW - TUBE - 0.01;
      const pivot: Tuple3 = [x, top, 0];
      const tilted = (p: Tuple3, s: Tuple3) =>
        add("wood", tiltX(p, TILT, pivot), s, [TILT, 0, 0]);
      tilted([x, top - TRAY_WALL / 2, 0], [w, TRAY_WALL, TRAY_DEPTH]);
      tilted([x, top + TRAY_LIP / 2, TRAY_DEPTH / 2], [w, TRAY_LIP, TRAY_WALL]);
      tilted([x, top + TRAY_LIP / 2, -TRAY_DEPTH / 2], [w, TRAY_LIP, TRAY_WALL]);
      for (const side of [-1, 1]) {
        tilted([x + side * (w / 2 - TRAY_WALL / 2), top + TRAY_LIP / 2, 0], [TRAY_WALL, TRAY_LIP, TRAY_DEPTH]);
      }
      // Hand-hold slot in the front lip.
      add("cabinetDark", tiltX([x, top + TRAY_LIP * 0.65, TRAY_DEPTH / 2 + 0.007], TILT, pivot), [0.12, 0.025, 0.003], [
        TILT,
        0,
        0,
      ]);
    }
  }
  return parts;
})();

/** Inside of each tilted tray. */
export const PRODUCE_RACK_SURFACES: StockSurface[] = PRODUCE_RACK.trayTops.flatMap((top) =>
  Array.from({ length: BAYS }, (_, i): StockSurface => ({
    kind: STOCK_KIND.Fruit,
    center: [-W / 2 + (i + 0.5) * BW, top, 0],
    width: BW - TUBE - 0.01 - 2 * TRAY_WALL,
    depth: TRAY_DEPTH - 2 * TRAY_WALL,
    maxHeight: TRAY_LIP + 0.03,
    tilt: TILT,
    slots: 1,
  })),
);

export function ProduceRack() {
  return <Parts parts={PARTS} />;
}
