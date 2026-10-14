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

/** GLB models stock items can be drawn with instead of a primitive (`scene/entities/stock/models.ts`). */
export const STOCK_MODEL = {
  Apple: "apple",
  Bag: "bag",
  BagFlat: "bag-flat",
  BananaBunch: "banana-bunch",
  BottleOil: "bottle-oil",
  Can: "can",
  Fish: "fish",
  IceCreamTub: "ice-cream-cup",
  IceLolly: "popsicle",
  Jar: "honey",
  Lemon: "lemon",
  Orange: "orange",
  MeatTray: "meat-raw",
  PeanutButter: "peanut-butter",
  Ribs: "meat-ribs",
  Sausages: "meat-sausage",
  // Snackies (loafbrr, CC0): printed packaging, one file.
  CerealTall: "snack-cereal-a",
  CerealWide: "snack-cereal-b",
  CerealFamily: "snack-cereal-c",
  ChipsClassic: "snack-chips-a",
  ChipsOriginal: "snack-chips-b",
  ChipsChunky: "snack-chips-d",
  CookiesBox: "snack-cookies-a",
  BiscuitsBox: "snack-cookies-b",
  CookiesTube: "snack-cookies-c",
  MilkBlue: "snack-milk-a",
  MilkGreen: "snack-milk-b",
  JuiceSmall: "snack-juice-a",
  JuiceSlim: "snack-juice-b",
  JuiceTall: "snack-juice-c",
} as const;
export type StockModelId = (typeof STOCK_MODEL)[keyof typeof STOCK_MODEL];

/** How stock items are drawn; `?assets=primitive` turns the GLB models off. */
export const ASSETS_MODE = {
  Models: "models",
  Primitive: "primitive",
} as const;
export type AssetsMode = (typeof ASSETS_MODE)[keyof typeof ASSETS_MODE];
