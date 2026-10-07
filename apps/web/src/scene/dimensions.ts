/** Meters. Y is up. The floor top sits on the XZ plane at y = 0. */
export const STORE_FLOOR = {
  width: 10,
  depth: 8,
  thickness: 0.08,
} as const;

export const SHELF = {
  width: 2.4,
  depth: 0.45,
  height: 1.8,
  post: 0.06,
  board: 0.04,
} as const;

/** Top face of the deck that slot positions sit on. Shared by the fixture and the shelf mesh. */
export const MIDDLE_DECK_TOP = 1.05;
