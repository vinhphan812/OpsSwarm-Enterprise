import { AGENT_FOCUS_IDLE_MS } from "@/constants/camera.constant";
import { ENTITY_TYPE, type EntityType } from "@/enums/scene.enum";
import { storeLayout } from "@/scene/layout";
import type { ActivityEntry, ControlStage } from "@/types/agent.type";

/** What the agent's camera focus goes to, and the caption it shows. */
export type AgentFocus = { entityId: string; entityType: EntityType; reason: string };

/** Stages whose entry moves the camera: where the agent looks into, acts on, and checks a product or fixture. */
export const FOCUS_STAGES: ReadonlySet<ControlStage> = new Set<ControlStage>(["INVESTIGATE", "ACT", "VERIFY"]);

/**
 * Where an activity entry points the camera: its product, else the shelf or piece of
 * equipment it names. Null for a stage that does not move the camera, or an entry
 * with neither.
 */
export function agentFocusOf(entry: ActivityEntry): AgentFocus | null {
  if (!FOCUS_STAGES.has(entry.stage)) return null;
  const reason = entry.summary;
  if (entry.sku) return { entityId: entry.sku, entityType: ENTITY_TYPE.Product, reason };
  if (!entry.shelf_id) return null;
  return { entityId: entry.shelf_id, entityType: fixtureTypeOf(entry.shelf_id), reason };
}

/** Whether `holderId` names a piece of equipment or a gondola shelf. */
export function fixtureTypeOf(holderId: string): EntityType {
  return storeLayout.equipment.some((item) => item.equipmentId === holderId) ? ENTITY_TYPE.Equipment : ENTITY_TYPE.Shelf;
}

/**
 * Milliseconds the agent should still wait before moving the camera: while the user drags
 * it, and for `AGENT_FOCUS_IDLE_MS` after they last used it. 0 when it may move now.
 */
export function agentFocusWait(ui: { userDragging: boolean; userActiveAt: number }, now: number): number {
  if (ui.userDragging) return AGENT_FOCUS_IDLE_MS;
  return Math.max(0, ui.userActiveAt + AGENT_FOCUS_IDLE_MS - now);
}
