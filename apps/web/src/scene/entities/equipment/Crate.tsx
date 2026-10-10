import { CRATE } from "@/constants/dimensions.constant";
import { Parts, partBuilder } from "./parts";

const WALL = 0.015;

/** Stacking crate with vented walls and hand holds. */
const PLASTIC = (() => {
  const { width: W, depth: D, height: H } = CRATE.plastic;
  const { parts, add } = partBuilder();
  add("plastic", [0, WALL / 2, 0], [W, WALL, D]);
  for (const side of [-1, 1]) {
    add("plastic", [0, H / 2, side * (D / 2 - WALL / 2)], [W, H, WALL]);
    add("plastic", [side * (W / 2 - WALL / 2), H / 2, 0], [WALL, H, D - 2 * WALL]);
    // Thicker top rim.
    add("plastic", [0, H - 0.015, side * (D / 2 - 0.004)], [W + 0.008, 0.03, WALL + 0.008]);
    // Vents along the long walls, drawn as dark insets on both faces.
    for (let i = 0; i < 7; i += 1) {
      const x = -W / 2 + 0.07 + (i * (W - 0.14)) / 6;
      add("plasticShade", [x, H * 0.45, side * (D / 2 - WALL / 2)], [0.025, H * 0.45, WALL + 0.004]);
    }
    add("plasticShade", [side * (W / 2 - WALL / 2), H - 0.07, 0], [WALL + 0.004, 0.035, 0.14]);
  }
  return parts;
})();

/** Slatted wooden fruit crate. */
const WOOD = (() => {
  const { width: W, depth: D, height: H } = CRATE.wood;
  const { parts, add } = partBuilder();
  const POST = 0.035;
  const SLAT = 0.07;
  for (const sx of [-1, 1]) {
    for (const sz of [-1, 1]) {
      add("woodDark", [sx * (W / 2 - POST / 2), H / 2, sz * (D / 2 - POST / 2)], [POST, H, POST]);
    }
  }
  for (const y of [0.05, 0.14, 0.23]) {
    for (const side of [-1, 1]) {
      add("woodDark", [0, y, side * (D / 2 - 0.006)], [W - 0.004, SLAT, 0.012]);
    }
  }
  for (const y of [0.05, H - 0.05]) {
    for (const side of [-1, 1]) {
      add("woodDark", [side * (W / 2 - 0.006), y, 0], [0.012, SLAT + 0.02, D - 0.004]);
    }
  }
  for (const z of [-0.12, 0, 0.12]) add("woodDark", [0, 0.008, z], [W - 0.02, 0.012, 0.1]);
  return parts;
})();

export function Crate({ variant }: { variant: "plastic" | "wood" }) {
  return <Parts parts={variant === "plastic" ? PLASTIC : WOOD} />;
}
