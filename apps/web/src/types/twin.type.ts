/** Live Twin state as `GET /store` serves it (apps/api `StoreResponse`). */

export type ProductInventory = {
  store_id: string;
  sku: string;
  shelf_id: string;
  slot_id: string;
  facings: number;
  shelf_quantity: number;
  backroom_quantity: number;
  version: number;
};

export type StoreResponse = {
  store_id: string;
  context_version: string;
  version: string;
  products: ProductInventory[];
};
