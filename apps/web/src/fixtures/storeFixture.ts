import { FACING } from "@/constants/scene.constant";
import {
  ENTITY_TYPE,
  EQUIPMENT_KIND,
  STOCK_KIND,
  type EquipmentKind,
  type FixtureKind,
} from "@/enums/scene.enum";
import { surfacePoint, surfacesOf } from "@/scene/entities/stock/surfaces";
import type { EquipmentFixture, ShelfFixture, SlotFixture, StoreFixture } from "@/types/scene.type";
import { padId } from "@/core/utils/ids";

const { Checkout, Barrier, GlassDoorCooler, OpenChiller, ProduceRack, CrateWood, CratePlastic } =
  EQUIPMENT_KIND;

/**
 * Splits every display surface of a fixture into slots, numbered across the
 * fixture as `<fixtureId>-S01`, `-S02`, ...
 */
function slotsFor(fixtureId: string, kind: FixtureKind): SlotFixture[] {
  const slots = surfacesOf(kind).flatMap((surface, index) => {
    const width = surface.width / surface.slots;
    return Array.from({ length: surface.slots }, (_, k) => {
      const offset = -surface.width / 2 + (k + 0.5) * width;
      const front = surfacePoint(surface, offset, 0, surface.depth / 2);
      return { position: { x: front.x, y: front.y, z: front.z }, surface: index, offset, width };
    });
  });
  return slots.map((slot, i) => ({ slotId: `${fixtureId}-${padId("S", i + 1)}`, ...slot }));
}

/** A double-sided gondola of packaged goods, front facing +Z. */
function shelf(shelfId: string, x: number, z: number, color: string): ShelfFixture {
  return {
    shelfId,
    position: { x, y: 0, z },
    rotationY: FACING.South,
    category: STOCK_KIND.Packaged,
    color,
    slots: slotsFor(shelfId, ENTITY_TYPE.Shelf),
  };
}

function place(
  equipmentId: string,
  kind: EquipmentKind,
  x: number,
  z: number,
  rotationY: number = FACING.South,
  y = 0,
): EquipmentFixture {
  return { equipmentId, kind, position: { x, y, z }, rotationY, slots: slotsFor(equipmentId, kind) };
}

/**
 * Store furniture, laid out like a small modern supermarket. The room is
 * 14 m x 11 m with the shopper door on the back wall at x = 4.4.
 *
 * - Checkouts: three lanes along the back wall, running toward it. Shoppers
 *   enter a lane from the shop floor, pay, and leave along an exit corridor
 *   behind the counters to the left door leaf.
 * - Barriers: lane rails, a door divider (exit left, entry right), and a cross
 *   rail so the exit area is reached only through the checkout lanes.
 * - Gondolas: 3 x 3 double-sided gondolas with 1.3-1.4 m aisles.
 * - Chilled wall: glass-door coolers then open chillers along the right wall.
 * - Fresh produce: leaning racks along the glass wall for daylight, closed
 *   off by a tiered display of empty wooden crates (decor, no stock).
 * - Backstock: plastic crates in the corner beside the door.
 */
const equipment: EquipmentFixture[] = [
  // Checkout lanes run toward the slat wall. Each counter's belt end faces the
  // shop floor and its shopper side faces +X; the cashier stands on the -X side.
  //   CK03: cashier -5.4..-4.6, counter -4.6..-3.6, lane -3.6..-2.7
  //   CK01: cashier -2.7..-1.9, counter -1.9..-0.9, lane -0.9..0
  //   CK02: cashier  0..0.8,    counter  0.8..1.8,  lane  1.8..2.7
  place("CK03", Checkout, -4.1, -3.15, FACING.East),
  place("CK01", Checkout, -1.4, -3.15, FACING.East),
  place("CK02", Checkout, 1.3, -3.15, FACING.East),
  // Lane rails along the shopper side of each lane.
  place("BR07", Barrier, -2.7, -3.0, FACING.East),
  place("BR01", Barrier, 0, -3.0, FACING.East),
  place("BR02", Barrier, 2.7, -3.0, FACING.East),
  // Door divider: exit leaf on the left, entry leaf on the right.
  place("BR03", Barrier, 4.4, -4.6, FACING.East),
  place("BR04", Barrier, 4.4, -3.0, FACING.East),
  // Cross rail closing the exit area off from the shop floor.
  place("BR05", Barrier, 3.55, -2.2),
  // Outer rail of the entry lane.
  place("BR06", Barrier, 5.5, -4.6, FACING.East),

  place("GDC01", GlassDoorCooler, 6.59, -3.4, FACING.West),
  place("GDC02", GlassDoorCooler, 6.59, -2.1, FACING.West),
  place("GDC03", GlassDoorCooler, 6.59, -0.8, FACING.West),
  place("OC01", OpenChiller, 6.525, 0.75, FACING.West),
  place("OC02", OpenChiller, 6.525, 2.3, FACING.West),
  place("OC03", OpenChiller, 6.525, 3.85, FACING.West),

  place("PR01", ProduceRack, -6.55, -3.2, FACING.East),
  place("PR02", ProduceRack, -6.55, -1.1, FACING.East),
  place("PR03", ProduceRack, -6.55, 1.0, FACING.East),

  // Tiered crate display closing the produce run along the glass wall:
  // a two-high back row against the glass and a single front row.
  ...[2.35, 2.92, 3.49, 4.06].flatMap((z, i) => [
    place(padId("CW", i * 3 + 1), CrateWood, -6.75, z, FACING.East),
    place(padId("CW", i * 3 + 2), CrateWood, -6.75, z, FACING.East, 0.28),
    place(padId("CW", i * 3 + 3), CrateWood, -6.36, z, FACING.East),
  ]),

  place("CP01", CratePlastic, 6.3, -5.15),
  place("CP02", CratePlastic, 6.3, -5.15, FACING.South, 0.3),
  place("CP03", CratePlastic, 6.3, -4.7),
];

/** Row letter, center z, and category color of each row of double-sided gondolas. */
const SHELF_ROWS = [
  { row: "A", z: -0.54, color: "#8d6e63" },
  { row: "B", z: 1.68, color: "#6d8b74" },
  { row: "C", z: 3.9, color: "#5f86a6" },
] as const;
const SHELF_COLUMNS_X = [-3.4, 0, 3.4] as const;

const shelves: ShelfFixture[] = SHELF_ROWS.flatMap(({ row, z, color }) =>
  SHELF_COLUMNS_X.map((x, i) => shelf(padId(row, i + 1), x, z, color)),
);

/**
 * Store layout (docs/adr/0007): shelves and equipment, no products. The scene takes
 * products from twin state.
 */
export const storeFixture: StoreFixture = {
  storeId: "store-001",
  shelves,
  equipment,
  products: [],
};
