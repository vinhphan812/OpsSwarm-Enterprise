import type { EquipmentKind } from "@/enums/scene.enum";
import type { Tuple3 } from "@/types/scene.type";

/** Meters. Y is up. The floor top sits on the XZ plane at y = 0. */
export const STORE_FLOOR = {
  width: 14,
  depth: 11,
  thickness: 0.08,
} as const;

/** U-shaped shell: back wall at -Z, side walls at ±X, front (+Z) left open for the camera. */
export const STORE_WALL = {
  height: 3.2,
  thickness: 0.25,
  /** Dark section strip on top of the walls. */
  cap: 0.02,
  /** Recessed reveal at the base, in place of a skirting board. */
  shadowGap: 0.04,
  shadowGapDepth: 0.02,
} as const;

/** Vertical wood battens on the back wall. */
export const WALL_SLATS = {
  panelWidth: 4.8,
  pitch: 0.09,
  width: 0.045,
  depth: 0.035,
} as const;

/** Black-framed glazing: a floor-to-lintel glass wall on the left, a sliding door on the back wall. */
export const GLAZING = {
  frame: 0.05,
  paneWidth: 1.6,
  transom: 2.45,
  windowHeight: 2.9,
  /** Solid wall kept at each end of the glass wall. */
  endPier: 0.6,
  doorHeight: 2.6,
  doorWidth: 2.2,
  /** Door center along the back wall, right of the slat panel. */
  doorX: 4.4,
} as const;

/**
 * Double-sided gondola: two open metal-frame shelving runs with wood boards,
 * back to back. The +Z side carries the slots.
 */
export const SHELF = {
  width: 2.4,
  /** Whole gondola, both sides and the gap between them. */
  depth: 0.92,
  /** One shelving side. */
  sideDepth: 0.45,
  height: 1.8,
  bays: 3,
  post: 0.04,
  board: 0.025,
  /** Deck tops, bottom to top. */
  deckTops: [0.12, 0.43, 0.74, 1.05, 1.36, 1.67],
} as const;

/** Center of each shelving side from the gondola center line, along Z. */
export const SHELF_SIDE_Z = SHELF.depth / 2 - SHELF.sideDepth / 2;

/** Leaning frame with wooden produce trays tilted toward the shopper. */
export const PRODUCE_RACK = {
  bays: 3,
  bayWidth: 0.62,
  depth: 0.6,
  frontHeight: 1.2,
  backHeight: 1.45,
  /** Tray tilt in radians, front edge down. */
  tilt: 0.3,
  trayTops: [0.32, 0.72, 1.12],
} as const;

/** Upright cooler with two hinged glass doors and a lit header. */
export const GLASS_DOOR_COOLER = {
  width: 1.25,
  height: 2.05,
  depth: 0.72,
  shelves: [0.42, 0.72, 1.02, 1.32, 1.62],
} as const;

/** Open-front multideck chiller with a canopy. */
export const OPEN_CHILLER = {
  width: 1.5,
  height: 2.1,
  depth: 0.85,
  shelves: [0.62, 0.86, 1.1, 1.34, 1.58],
} as const;

/** Checkout counter: belt, scanner and scale, bagging well. Long axis along X. */
export const CHECKOUT = {
  length: 1.9,
  depth: 1.0,
  height: 0.9,
} as const;

/** Lane light on a pole at the belt end of a checkout: lit while the lane is staffed. */
export const LANE_LIGHT = {
  /** Pole height above the counter top, up to the lamp's bottom collar. */
  poleHeight: 0.72,
  poleRadius: 0.011,
  /** Flange that bolts the pole to the counter. */
  baseRadius: 0.035,
  baseHeight: 0.008,
  /** Dark collar under and cap over the diffuser. */
  collarRadius: 0.05,
  collarHeight: 0.018,
  /** Frosted shade the light shows through. */
  diffuserRadius: 0.044,
  diffuserHeight: 0.11,
  /** Bright core inside the shade. */
  coreRadius: 0.026,
  /** Pole center in from the counter's belt end and cashier-side edge. */
  inset: 0.07,
} as const;

/** Height of a lane light above the counter top, cap included. */
export const LANE_LIGHT_HEIGHT =
  LANE_LIGHT.poleHeight + 2 * LANE_LIGHT.collarHeight + LANE_LIGHT.diffuserHeight;

export const CRATE = {
  plastic: { width: 0.6, depth: 0.4, height: 0.3 },
  wood: { width: 0.55, depth: 0.38, height: 0.28 },
} as const;

/** Freestanding guide rail for queues and entrances. */
export const BARRIER = {
  length: 1.6,
  height: 1.0,
} as const;

/** Bounding box of each equipment kind in its own frame: [x, y, z] extents, front at +Z. */
export const EQUIPMENT_SIZE = {
  "produce-rack": [PRODUCE_RACK.bays * PRODUCE_RACK.bayWidth, PRODUCE_RACK.backHeight, PRODUCE_RACK.depth],
  "glass-door-cooler": [GLASS_DOOR_COOLER.width, GLASS_DOOR_COOLER.height, GLASS_DOOR_COOLER.depth],
  "open-chiller": [OPEN_CHILLER.width, OPEN_CHILLER.height, OPEN_CHILLER.depth],
  checkout: [CHECKOUT.length, CHECKOUT.height + LANE_LIGHT_HEIGHT, CHECKOUT.depth],
  "crate-plastic": [CRATE.plastic.width, CRATE.plastic.height, CRATE.plastic.depth],
  "crate-wood": [CRATE.wood.width, CRATE.wood.height, CRATE.wood.depth],
  barrier: [BARRIER.length, BARRIER.height, 0.1],
} as const satisfies Record<EquipmentKind, Readonly<Tuple3>>;
