import { ANOMALY_SEVERITY, type AnomalySeverity } from "@/enums/anomaly.enum";
import { RISK_BAND, type RiskBand } from "@/enums/ui.enum";

/**
 * A color of the App.css `@theme` palette, for code that cannot use CSS, such as
 * three.js materials. Read once per token, so call it after the stylesheet has
 * loaded (while rendering, not at module load). `fallback` stands in where there is
 * no document or the token is missing.
 */
const cache = new Map<string, string>();

export function themeColor(token: string, fallback: string): string {
  let color = cache.get(token);
  if (color === undefined) {
    const value = typeof document === "undefined"
      ? ""
      : getComputedStyle(document.documentElement).getPropertyValue(token).trim();
    color = value || fallback;
    if (value) cache.set(token, color);
  }
  return color;
}

/** Status colors of the palette, for the 3D scene. */
export const goodColor = () => themeColor("--color-good", "#0ca30c");
export const warningColor = () => themeColor("--color-warning", "#fab219");

/** Glow color of the selected entity, from the `--color-selection` theme token. */
export const selectionColor = () => themeColor("--color-selection", "#ffffff");

/** Outline and slot light of a recent change in the scene, from the `--color-change` theme token. */
export const changeColor = () => themeColor("--color-change", "#3987e5");

/** The line from a moved product's old slot to its new one, from the `--color-move` theme token. */
export const moveColor = () => themeColor("--color-move", "#9d5cff");

const ANOMALY_FALLBACK: Record<AnomalySeverity, string> = {
  [ANOMALY_SEVERITY.Critical]: "#e5177e",
  [ANOMALY_SEVERITY.High]: "#ff4d3d",
  [ANOMALY_SEVERITY.Medium]: "#ff9f1a",
  [ANOMALY_SEVERITY.Low]: "#f2d34b",
};

/** Halo color of an anomaly of `severity`, from the `--color-anomaly-<severity>` theme tokens. */
export const anomalyColor = (severity: AnomalySeverity) =>
  themeColor(`--color-anomaly-${severity}`, ANOMALY_FALLBACK[severity]);

const RISK_FALLBACK: Record<RiskBand, string> = {
  [RISK_BAND.Low]: "#0ca30c",
  [RISK_BAND.Elevated]: "#fab219",
  [RISK_BAND.High]: "#ff8a1f",
  [RISK_BAND.Severe]: "#ff3b30",
};

/** Slot tint of a stockout-risk band, from the `--color-risk-<band>` theme tokens. */
export const riskBandColor = (band: RiskBand) => themeColor(`--color-risk-${band}`, RISK_FALLBACK[band]);
