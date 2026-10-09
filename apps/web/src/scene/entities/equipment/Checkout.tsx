import { CHECKOUT } from "@/constants/dimensions.constant";
import { Parts, partBuilder } from "./parts";

const { length: L, depth: D, height: H } = CHECKOUT;
const RIM = 0.05;
const RIM_H = 0.04;
const TOP = H - RIM_H;

/** Belt, then scanner and scale, then a split bagging well, left to right. */
const BELT = { from: -L / 2 + RIM, to: -0.1 };
const SCALE = { from: -0.1, to: 0.3 };
const BAGGING = { from: 0.3, to: L / 2 - RIM };

/**
 * Checkout counter. Shoppers stand at the front (+Z); the cashier stands behind it.
 * Long axis along X.
 */
const PARTS = (() => {
  const { parts, add } = partBuilder();
  const span = (r: { from: number; to: number }) => ({ x: (r.from + r.to) / 2, w: r.to - r.from });

  add("cabinet", [0, TOP / 2, 0], [L, TOP, D]);
  add("cabinetDark", [0, 0.04, 0.02], [L - 0.04, 0.08, D - 0.02]);

  // Raised rim around the top and between the stations.
  add("steel", [0, H - RIM_H / 2, D / 2 - RIM / 2], [L, RIM_H, RIM]);
  add("steel", [0, H - RIM_H / 2, -D / 2 + RIM / 2], [L, RIM_H, RIM]);
  for (const x of [-L / 2 + RIM / 2, L / 2 - RIM / 2, SCALE.from, SCALE.to]) {
    add("steel", [x, H - RIM_H / 2, 0], [RIM * 0.6, RIM_H, D - 2 * RIM]);
  }

  const belt = span(BELT);
  add("rubber", [belt.x, TOP + 0.004, 0], [belt.w - 0.02, 0.008, D - 2 * RIM - 0.02]);
  // Belt rollers at each end.
  for (const x of [BELT.from + 0.04, BELT.to - 0.04]) {
    add("cabinetDark", [x, TOP + 0.01, 0], [0.04, 0.02, D - 2 * RIM - 0.02]);
  }

  const scale = span(SCALE);
  add("screen", [scale.x, TOP + 0.006, 0.08], [scale.w - 0.08, 0.012, 0.36]);
  add("frame", [scale.x, TOP + 0.003, -0.25], [scale.w - 0.08, 0.006, 0.22]);
  // Customer display on a pole at the back of the scale.
  add("frame", [scale.x, H + 0.2, -D / 2 + 0.14], [0.04, 0.4, 0.04]);
  add("frame", [scale.x, H + 0.42, -D / 2 + 0.15], [0.26, 0.18, 0.04], [-0.25, 0, 0]);
  add("screen", [scale.x, H + 0.424, -D / 2 + 0.172], [0.22, 0.14, 0.004], [-0.25, 0, 0]);
  // Card reader on the shopper side.
  add("frame", [SCALE.to - 0.06, H + 0.04, D / 2 - 0.1], [0.08, 0.08, 0.12], [-0.4, 0, 0]);

  const bagging = span(BAGGING);
  add("rubber", [bagging.x, TOP + 0.003, 0], [bagging.w - 0.02, 0.006, D - 2 * RIM - 0.02]);
  add("steel", [bagging.x, H - RIM_H / 2, 0], [bagging.w, RIM_H, RIM * 0.6]);

  // Cash register on the cashier half of the bagging well: drawer, keyboard
  // nearest the cashier, and a screen tilted back toward them.
  const posX = bagging.x;
  const drawerTop = H + 0.1;
  add("cabinetDark", [posX, H + 0.05, -0.27], [0.42, 0.1, 0.36]);
  add("frame", [posX, drawerTop + 0.01, -0.38], [0.3, 0.02, 0.1]);
  add("frame", [posX, drawerTop + 0.08, -0.16], [0.04, 0.16, 0.04]);
  add("frame", [posX, drawerTop + 0.24, -0.16], [0.32, 0.22, 0.03], [0.25, 0, 0]);
  add("screen", [posX, drawerTop + 0.236, -0.177], [0.28, 0.18, 0.004], [0.25, 0, 0]);
  return parts;
})();

export function Checkout() {
  return <Parts parts={PARTS} />;
}
