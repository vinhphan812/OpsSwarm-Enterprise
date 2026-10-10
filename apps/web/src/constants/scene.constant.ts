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

/** Sky color behind the store, also the fog color so the lawn fades into it. */
export const SKY_COLOR = "#dfe7ec";

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

/** Size of the lawn plane around the store, in meters. */
export const GROUND_SIZE = 80;
export const LAWN_COLOR = "#b9c3a8";

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
