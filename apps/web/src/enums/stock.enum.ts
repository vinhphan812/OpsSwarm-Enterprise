/** Unit primitives every stock item is scaled from. */
export const STOCK_SHAPE = {
  Box: "box",
  Cylinder: "cylinder",
  Sphere: "sphere",
} as const;
export type StockShape = (typeof STOCK_SHAPE)[keyof typeof STOCK_SHAPE];

/** How full a product's slot is, from its shelf stock and facings. */
export const STOCK_STATE = {
  Ok: "ok",
  Low: "low",
  Out: "out",
} as const;
export type StockState = (typeof STOCK_STATE)[keyof typeof STOCK_STATE];
