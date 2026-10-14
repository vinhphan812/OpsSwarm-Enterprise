import { FIXTURE_P001 } from "@/constants/twin.constant";
import { mulberry32 } from "@/core/utils/random";
import { ENTITY_TYPE, type FixtureKind } from "@/enums/scene.enum";
import { capacityOf } from "@/scene/entities/stock/capacity";
import { slotUnits } from "@/scene/entities/stock/placement";
import { surfacesOf } from "@/scene/entities/stock/surfaces";
import { storeLayout } from "@/scene/layout";
import type { ProductInventory, StoreResponse } from "@/types/twin.type";

/**
 * Demo data for `?twin=demo` (development builds only), never Live Twin truth.
 * `GET /store` for a stocked store: P001 from the API fixture and a product on every
 * kind of fixture that holds stock, some of them out of stock or low.
 */

const STORE_ID = FIXTURE_P001.store_id;
const VERSION = "v1";

type ProductRow = [sku: string, shelfId: string, slotId: string, facings: number, shelf: number, backroom: number];

/** Gondola slots S19–S24 are the front side's eye-level deck, so the items are easy to see. */
const PRODUCTS: ProductRow[] = [
  ["P002", "A01", "A01-S20", 2, 10, 10],
  ["P003", "A01", "A01-S21", 2, 0, 18],
  ["P004", "A02", "A02-S19", 3, 2, 30],
  ["P005", "A03", "A03-S22", 2, 12, 40],
  ["P006", "B01", "B01-S19", 3, 9, 15],
  ["P007", "B02", "B02-S20", 2, 1, 0],
  ["P008", "C01", "C01-S21", 2, 14, 36],
  ["P009", "GDC01", "GDC01-S01", 2, 6, 12],
  ["P010", "OC01", "OC01-S01", 2, 0, 20],
  ["P011", "PR01", "PR01-S01", 4, 30, 60],
  ["P012", "PR02", "PR02-S01", 3, 18, 25],
  // P017 is left out: the demand-surge scenario and the SKU lookup use it as a SKU the store lacks.
  // Butcher's counter in the first glass-door cooler, above the chicken.
  ["P013", "GDC01", "GDC01-S07", 2, 6, 10],
  ["P014", "GDC01", "GDC01-S08", 2, 8, 12],
  ["P015", "GDC01", "GDC01-S05", 2, 3, 6],
  // Frozen desserts and fries in the first open chiller, beside the empty peas.
  ["P016", "OC01", "OC01-S02", 3, 9, 18],
  ["P018", "OC01", "OC01-S05", 3, 12, 24],
  ["P020", "OC01", "OC01-S03", 3, 9, 20],
];

/** Share of the free slots the filler stock takes, so the store looks trading, with a few gaps. */
const FILL_SHARE = 0.75;
/** Filler SKUs start here, clear of the named catalog. */
const FIRST_FILLER = 101;
/** Slots the demo's simulation moves products into (`simulation.ts`): left free for it. */
const MOVE_TARGETS = ["B02-S22", "A02-S22", "B01-S22"];

/**
 * Unnamed filler stock on the slots the named products leave free, so the demo store is
 * not mostly empty shelves. The same on every load. Each filler holds from about a third
 * to all of what its facings take (`slotUnits`), never less than its facings, so none is
 * low or out of stock and the demo's alerts stay the named products'. Fillers are on the
 * shelves only: they have no names, prices, or sales (`commerce.ts`, `checkouts.ts`).
 */
const FILLERS: ProductRow[] = (() => {
  const random = mulberry32(20261013);
  const taken = new Set([FIXTURE_P001.slot_id, ...PRODUCTS.map(([, , slotId]) => slotId), ...MOVE_TARGETS]);
  const holders: Array<{ id: string; kind: FixtureKind; slots: typeof storeLayout.shelves[number]["slots"] }> = [
    ...storeLayout.shelves.map((shelf) => ({ id: shelf.shelfId, kind: ENTITY_TYPE.Shelf as FixtureKind, slots: shelf.slots })),
    ...storeLayout.equipment.map((item) => ({ id: item.equipmentId, kind: item.kind as FixtureKind, slots: item.slots })),
  ];
  const rows: ProductRow[] = [];
  for (const holder of holders) {
    for (const slot of holder.slots) {
      const capacity = capacityOf(holder.kind, slot);
      const surface = surfacesOf(holder.kind)[slot.surface];
      // Draw every roll, so one slot's outcome does not shift the next one's.
      const [fill, trim, level, back] = [random(), random(), random(), random()];
      if (!surface || capacity === 0 || taken.has(slot.slotId) || fill >= FILL_SHARE) continue;
      const facings = Math.max(1, capacity - (trim < 0.3 ? 1 : 0));
      const full = slotUnits(surface, slot, facings);
      const shelf = Math.max(facings, Math.round(full * (0.35 + 0.65 * level)));
      const sku = `P${FIRST_FILLER + rows.length}`;
      rows.push([sku, holder.id, slot.slotId, facings, shelf, Math.round(full * (0.5 + 2 * back))]);
    }
  }
  return rows;
})();

/** The demo store. A new object per call. */
export function demoStoreState(): StoreResponse {
  return {
    store_id: STORE_ID,
    context_version: `${STORE_ID}:${VERSION}`,
    version: VERSION,
    products: [
      { ...FIXTURE_P001 },
      ...[...PRODUCTS, ...FILLERS].map(
        ([sku, shelf_id, slot_id, facings, shelf_quantity, backroom_quantity]): ProductInventory => ({
          store_id: STORE_ID,
          sku,
          shelf_id,
          slot_id,
          facings,
          shelf_quantity,
          backroom_quantity,
          version: 1,
        }),
      ),
    ],
  };
}
