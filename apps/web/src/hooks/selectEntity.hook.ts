import type { ThreeEvent } from "@react-three/fiber";
import type { EntityType } from "@/enums/scene.enum";
import { stockItemAt } from "@/scene/entities/stock/Stock";
import { isDrag } from "@/scene/utils/pointer";
import { useUiStore } from "@/state/ui.store";

/**
 * Click handler for a fixture's hit box: selects the fixture. A click on one of the
 * fixture's own stock items is left to the item, so the product gets selected instead.
 */
export function useSelectOnClick(entityId: string, entityType: EntityType) {
  return (event: ThreeEvent<MouseEvent>) => {
    if (isDrag(event)) return;
    const ownItem = event.intersections.some((hit) => stockItemAt(hit)?.holderId === entityId);
    if (ownItem) return;
    event.stopPropagation();
    useUiStore.getState().select(entityId, entityType);
  };
}
