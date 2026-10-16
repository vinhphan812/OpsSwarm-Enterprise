/** How many issues the issues notice lists before summing up the rest. */
export const ISSUES_SHOWN = 5;

/** Agent Activity panel width in px. Fixed: the panel does not resize. */
export const PANEL_WIDTH = 440;

/** How long a promotion card opened from a product's details stays flashed, in ms. */
export const PROMOTION_FLASH_MS = 2400;

/** Alerts the panel lists before "Show all"; the worst come first. */
export const ALERTS_SHOWN = 3;

/** Products the inventory card lists before "Show all"; out and low stock come first. */
export const STORE_STATUS_ROWS = 5;

/** How often the KPI strip reads today's revenue again, in ms. */
export const REVENUE_TODAY_REFRESH_MS = 60_000;

/** How old the last good read of today's revenue may get before the KPI strip stops showing it, in ms. */
export const REVENUE_TODAY_STALE_MS = 5 * 60_000;

/** How long the AI Impact toast stays over the 3D view, in ms. */
export const IMPACT_TOAST_MS = 8000;

/** KPI rows the AI Impact toast shows, in served order; the card in the panel shows them all. */
export const IMPACT_TOAST_ROWS = 3;
