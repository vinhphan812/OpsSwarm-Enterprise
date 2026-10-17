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

/** Layers the user can lay over the 3D view, each on or off on its own. */
export const OVERLAY = {
  StockoutRisk: "stockout_risk",
  AiChanges: "ai_changes",
} as const;
export type Overlay = (typeof OVERLAY)[keyof typeof OVERLAY];
export const OVERLAYS: readonly Overlay[] = Object.values(OVERLAY);

/** Bands of the stockout-risk overlay, lowest first: green, yellow, orange, red. */
export const RISK_BAND = {
  Low: "low",
  Elevated: "elevated",
  High: "high",
  Severe: "severe",
} as const;
export type RiskBand = (typeof RISK_BAND)[keyof typeof RISK_BAND];
export const RISK_BANDS: readonly RiskBand[] = Object.values(RISK_BAND);
