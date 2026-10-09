/**
 * Fixed value sets of the scene, as const objects: use `EQUIPMENT_KIND.Checkout`
 * in code, while the values stay plain strings in data.
 */

export const EQUIPMENT_KIND = {
  ProduceRack: "produce-rack",
  GlassDoorCooler: "glass-door-cooler",
  OpenChiller: "open-chiller",
  Checkout: "checkout",
  CratePlastic: "crate-plastic",
  CrateWood: "crate-wood",
  Barrier: "barrier",
} as const;
export type EquipmentKind = (typeof EQUIPMENT_KIND)[keyof typeof EQUIPMENT_KIND];

/** What a display surface holds. */
export const STOCK_KIND = {
  Packaged: "packaged",
  Fruit: "fruit",
  Fresh: "fresh",
  Frozen: "frozen",
} as const;
export type StockKind = (typeof STOCK_KIND)[keyof typeof STOCK_KIND];

/** Values of `userData.entityType` on tagged scene objects. */
export const ENTITY_TYPE = {
  Store: "store",
  Shelf: "shelf",
  Slot: "slot",
  Product: "product",
  Equipment: "equipment",
} as const;
export type EntityType = (typeof ENTITY_TYPE)[keyof typeof ENTITY_TYPE];

/** A fixture that holds products: a gondola or a piece of display equipment. */
export type FixtureKind = typeof ENTITY_TYPE.Shelf | EquipmentKind;
