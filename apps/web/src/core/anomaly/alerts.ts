import { fixtureTypeOf } from "@/core/agent/agentFocus";
import {
  ALERT_CATEGORY,
  ALERT_STEP,
  ANOMALY_TYPE,
  ANOMALY_SEVERITIES,
  type AlertCategory,
  type AlertStep,
} from "@/enums/anomaly.enum";
import { ENTITY_TYPE, type EntityType } from "@/enums/scene.enum";
import { storeLayout } from "@/scene/layout";
import type { ActivityEntry, ControlStage } from "@/types/agent.type";
import type { Anomaly } from "@/types/anomaly.type";

/** The lifecycle step each control stage puts an anomaly in. */
const STEP_OF_STAGE: Record<ControlStage, AlertStep> = {
  OBSERVE: ALERT_STEP.Detected,
  DETECT: ALERT_STEP.Detected,
  INVESTIGATE: ALERT_STEP.Investigating,
  PLAN: ALERT_STEP.Planning,
  SIMULATE: ALERT_STEP.Planning,
  GUARD: ALERT_STEP.Guarding,
  ACT: ALERT_STEP.Acting,
  VERIFY: ALERT_STEP.Verifying,
};

/** A demand surge is an opportunity; every other anomaly is an alert. */
export function alertCategory(anomaly: Pick<Anomaly, "anomaly_type">): AlertCategory {
  return anomaly.anomaly_type === ANOMALY_TYPE.DemandSurge ? ALERT_CATEGORY.Opportunity : ALERT_CATEGORY.Alert;
}

/**
 * How far the agent has handled `anomaly`: the stage of the latest timeline entry with its
 * correlation id. Detected while no entry has it; never guessed in the UI.
 */
export function alertStep(anomaly: Pick<Anomaly, "correlation_id">, activity: ActivityEntry[]): AlertStep {
  let latest: ActivityEntry | null = null;
  for (const entry of activity) {
    if (!anomaly.correlation_id || entry.correlation_id !== anomaly.correlation_id) continue;
    if (!latest || Date.parse(entry.ts) >= Date.parse(latest.ts)) latest = entry;
  }
  return latest ? STEP_OF_STAGE[latest.stage] : ALERT_STEP.Detected;
}

/** Worst severity first, then the newest. A new array. */
export function sortAlerts(anomalies: Anomaly[]): Anomaly[] {
  const rank = (anomaly: Anomaly) => ANOMALY_SEVERITIES.indexOf(anomaly.severity);
  return [...anomalies].sort(
    (a, b) => rank(b) - rank(a) || Date.parse(b.detected_at) - Date.parse(a.detected_at),
  );
}

/** The 3D entity an alert points at. */
export type AlertTarget = { entityId: string; entityType: EntityType };

/** Every gondola and piece of equipment of the store. */
const FIXTURE_IDS = new Set([
  ...storeLayout.shelves.map((shelf) => shelf.shelfId),
  ...storeLayout.equipment.map((item) => item.equipmentId),
]);

/**
 * What picking an alert focuses: its product while the twin on screen has it, else its
 * shelf or piece of equipment. Null when neither is in the store, so it cannot be shown.
 */
export function alertTarget(anomaly: Pick<Anomaly, "sku" | "shelf_id">, skusInTwin: ReadonlySet<string>): AlertTarget | null {
  if (anomaly.sku) return skusInTwin.has(anomaly.sku) ? { entityId: anomaly.sku, entityType: ENTITY_TYPE.Product } : null;
  if (anomaly.shelf_id && FIXTURE_IDS.has(anomaly.shelf_id)) {
    return { entityId: anomaly.shelf_id, entityType: fixtureTypeOf(anomaly.shelf_id) };
  }
  return null;
}
