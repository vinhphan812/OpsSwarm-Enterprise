export type HealthResponse = {
  status: "ok" | "degraded";
  service: "retailtwin-api";
  environment: string;
  store_id: string;
  fixture_loaded: boolean;
};

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

export type RetailTwinClient = {
  health: () => Promise<HealthResponse>;
  store: () => Promise<StoreResponse>;
  inventory: (sku: string) => Promise<ProductInventory>;
};
