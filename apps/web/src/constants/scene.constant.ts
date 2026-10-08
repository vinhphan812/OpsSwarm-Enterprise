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

/** Translation key of the merchandise group shown in hover labels for a kind of stock. */
export const stockLabelKey = (kind: StockKind) => `scene.stock.${kind}` as const;

/** Translation key of the hover label per equipment kind. Kinds without one (crates, barriers) show none. */
export const EQUIPMENT_LABEL: Partial<Record<EquipmentKind, `scene.stock.${StockKind}` | "scene.checkout">> = {
  [EQUIPMENT_KIND.ProduceRack]: stockLabelKey(STOCK_KIND.Fruit),
  [EQUIPMENT_KIND.GlassDoorCooler]: stockLabelKey(STOCK_KIND.Fresh),
  [EQUIPMENT_KIND.OpenChiller]: stockLabelKey(STOCK_KIND.Frozen),
  [EQUIPMENT_KIND.Checkout]: "scene.checkout",
};

/** Sky color behind the store, also the fog color so the lawn fades into it. */
export const SKY_COLOR = "#dfe7ec";

/** Gap between the top of an entity and its hover label, in meters. */
export const LABEL_LIFT = 0.25;

/** Height of the selected product's tag above its slot, in meters. */
export const TAG_LIFT = 0.32;

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
