/** Connection state of the live twin: loading until the first state, then ready; error when the first load fails. */
export const TWIN_STATUS = {
  Loading: "loading",
  Ready: "ready",
  Error: "error",
} as const;
export type TwinStatus = (typeof TWIN_STATUS)[keyof typeof TWIN_STATUS];

/** What the twin says about one product: not loaded yet, absent, broken, or fine. */
export const INSPECTION_KIND = {
  Loading: "loading",
  Missing: "missing",
  Invalid: "invalid",
  Ok: "ok",
} as const;
export type InspectionKind = (typeof INSPECTION_KIND)[keyof typeof INSPECTION_KIND];
