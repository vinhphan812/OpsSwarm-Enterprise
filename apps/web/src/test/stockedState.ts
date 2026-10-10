import { FIXTURE_P001 } from "@/constants/twin.constant";
import type { ProductInventory, StoreResponse } from "@/types/twin.type";

/**
 * `GET /store` for a stocked store: P001 from the API fixture and a product on every kind
 * of fixture that holds stock, some of them out of stock or low. Test data only; the app
 * shows no products until the API sends them.
 */

const STORE_ID = FIXTURE_P001.store_id;
const VERSION = "v1";
const CONTEXT_VERSION = `${STORE_ID}:${VERSION}`;

type ProductRow = [
  sku: string,
  shelfId: string,
  slotId: string,
  facings: number,
  shelf: number,
  backroom: number,
];

/**
 * Gondola slots S19–S24 are the front side's eye-level deck, so the items are easy to see.
 * One product per kind of fixture that holds stock: gondola, glass-door cooler, open chiller, produce racks.
 */
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
];

/** `GET /store` with P001 from the API fixture and a product on every kind of fixture. */
export function stockedStoreState(): StoreResponse {
  const products: ProductInventory[] = [
    { ...FIXTURE_P001 },
    ...PRODUCTS.map(
      ([
        sku,
        shelf_id,
        slot_id,
        facings,
        shelf_quantity,
        backroom_quantity,
      ]) => ({
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
  ];
  return {
    store_id: STORE_ID,
    context_version: CONTEXT_VERSION,
    version: VERSION,
    products,
  };
}
