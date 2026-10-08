/** Unit primitives every stock item is scaled from. */
export const STOCK_SHAPE = {
  Box: "box",
  Cylinder: "cylinder",
  Sphere: "sphere",
} as const;
export type StockShape = (typeof STOCK_SHAPE)[keyof typeof STOCK_SHAPE];
