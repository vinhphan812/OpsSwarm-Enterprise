import { EQUIPMENT_KIND, STOCK_KIND, type EquipmentKind, type StockKind } from "@/enums/scene.enum";

/** Turns about Y that point a fixture's front (+Z at rest) along a world axis. */
export const FACING = {
  /** Front faces +Z, toward the open side of the room. */
  South: 0,
  /** Front faces +X: against the left (glass) wall. */
  East: Math.PI / 2,
  /** Front faces -X: against the right wall. */
  West: -Math.PI / 2,
} as const;

/** Translation key of the merchandise group a kind of stock belongs to; the shelf card's title. */
export const stockLabelKey = (kind: StockKind) => `scene.stock.${kind}` as const;

/**
 * Translation key of the card title per equipment kind. Only these kinds can be selected;
 * crates and barriers have none.
 */
export const EQUIPMENT_TITLE: Partial<Record<EquipmentKind, `scene.stock.${StockKind}` | "scene.checkout">> = {
  [EQUIPMENT_KIND.ProduceRack]: stockLabelKey(STOCK_KIND.Fruit),
  [EQUIPMENT_KIND.GlassDoorCooler]: stockLabelKey(STOCK_KIND.Fresh),
  [EQUIPMENT_KIND.OpenChiller]: stockLabelKey(STOCK_KIND.Frozen),
  [EQUIPMENT_KIND.Checkout]: "scene.checkout",
};

/** Sky color at the horizon, also the fog color so the lawn fades into it. */
export const SKY_COLOR = "#dfe7ec";
/** Sky color overhead (`Sky`). */
export const SKY_ZENITH_COLOR = "#7fb2e0";

/** Emissive strength of a selected fixture's parts. */
export const SELECTION_GLOW = 0.55;
/** How much brighter a status light (a checkout's lane light) burns while its fixture is selected. */
export const SELECTION_STATUS_BOOST = 2.2;
/** Emissive strength of a selected product's items, which are small and need more. */
export const SELECTION_ITEM_GLOW = 0.8;
/** Emissive strength and opacity of the halo around a product with an open anomaly, at rest. */
export const ANOMALY_HALO_GLOW = 1.4;
export const ANOMALY_HALO_OPACITY = 0.68;
/** The halo pulses this many times a second, by this share of its rest value. */
export const ANOMALY_PULSE_HZ = 1.1;
export const ANOMALY_PULSE_DEPTH = 0.45;
/** A press that moves the pointer more than this many pixels is a camera drag, not a click. */
export const CLICK_SLOP_PX = 4;

/** Size of the lawn plane around the store, in meters: past the fog's far end, so its edge never shows. */
export const GROUND_SIZE = 240;
export const LAWN_COLOR = "#a9c28b";

/** Warm matte white plaster. */
export const WALL_COLOR = "#f3f1ed";
/** Cut-through section on top of the walls, like an architectural model. */
export const WALL_CAP_COLOR = "#2b2d31";
/** Recessed shadow gap at the base instead of a skirting board. */
export const WALL_GAP_COLOR = "#3a3b3e";
export const WALL_SLAT_COLOR = "#8b6b4e";

/** Black powder-coated aluminium, the usual modern-house frame. */
export const GLAZING_FRAME_COLOR = "#1d1e20";

/** Flat floor fallback when no canvas is available (unit tests). */
export const FLOOR_WOOD_COLOR = "#cbb69c";

/** Opacity of the outline a moved product leaves at its source slot while the move is recent. */
export const MOVE_GHOST_OPACITY = 0.85;
/** Emissive strength and opacity of the light over a moved product's source and destination slots. */
export const MOVE_SLOT_GLOW = 0.9;
export const MOVE_SLOT_OPACITY = 0.4;
/** How high a moved product's items rise midway through their tween, in meters. */
export const MOVE_ARC_HEIGHT = 0.18;
/** How much of its light a slot hands over during a move: the source dims and the destination brightens by this share. */
export const MOVE_SLOT_HANDOFF = 0.7;
/** Extra glow on the destination slot the moment the items land, fading with the marks. */
export const MOVE_ARRIVAL_FLASH = 1.5;
/** Opacity of the translucent box a moved product leaves at its source slot, under its outline. */
export const MOVE_GHOST_FILL_OPACITY = 0.22;
/** How far above a slot's surface a move's arrow starts and ends, in meters. */
export const MOVE_ARROW_LIFT = 0.12;
/** How far a move's arrow clears the higher of its two ends, in meters, plus `MOVE_ARROW_RISE` per meter travelled. */
export const MOVE_ARROW_CLEARANCE = 0.3;
export const MOVE_ARROW_RISE = 0.06;
/** Width of a move arrow's line, and of the dark outline under it, in screen pixels: the same at any zoom. */
export const MOVE_ARROW_WIDTH_PX = 3.5;
export const MOVE_ARROW_OUTLINE_PX = 5.5;
/** Opacity at full strength of a move arrow's line, and of the dark outline under it. */
export const MOVE_ARROW_OPACITY = 0.95;
export const MOVE_ARROW_OUTLINE_OPACITY = 0.45;
/** The ease-out-back constant of a new item's growth: 1.7 takes it about 10% past full size before it settles. */
export const ARRIVAL_OVERSHOOT = 1.7;
