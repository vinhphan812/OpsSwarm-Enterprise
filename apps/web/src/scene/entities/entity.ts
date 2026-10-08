import type { EntityType } from "@/scene/types";

export function entityProps(entityId: string, entityType: EntityType) {
  return {
    name: entityId,
    userData: { entityId, entityType },
  };
}
