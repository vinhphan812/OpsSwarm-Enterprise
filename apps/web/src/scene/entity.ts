import type { EntityType } from "./types";

export function entityProps(entityId: string, entityType: EntityType) {
  return {
    name: entityId,
    userData: { entityId, entityType },
  };
}
