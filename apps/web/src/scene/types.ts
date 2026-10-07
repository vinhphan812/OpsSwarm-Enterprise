export type Vec3 = {
  x: number;
  y: number;
  z: number;
};

export type SlotFixture = {
  slotId: string;
  position: Vec3;
};

export type ShelfFixture = {
  shelfId: string;
  position: Vec3;
  color: string;
  slots: SlotFixture[];
};

export type ProductFixture = {
  productId: string;
  sku: string;
  shelfId: string;
  slotId: string;
  facings: number;
  color: string;
};

export type StoreFixture = {
  storeId: string;
  shelves: ShelfFixture[];
  products: ProductFixture[];
};

export type EntityType = "store" | "shelf" | "slot" | "product";
