/** Which twin state the scene shows. */
export const VIEW_MODE = {
  Live: "live",
  Simulation: "simulation",
} as const;
export type ViewMode = (typeof VIEW_MODE)[keyof typeof VIEW_MODE];

/** What the floating panel and the view switcher focus on. */
export const LENS = {
  Operations: "operations",
  Revenue: "revenue",
  Promotions: "promotions",
} as const;
export type Lens = (typeof LENS)[keyof typeof LENS];
export const LENSES: readonly Lens[] = Object.values(LENS);

/** Who moved the selection: the user, or the agent through `focusEntity`. */
export const FOCUS_SOURCE = {
  User: "user",
  Agent: "agent",
} as const;
export type FocusSource = (typeof FOCUS_SOURCE)[keyof typeof FOCUS_SOURCE];
