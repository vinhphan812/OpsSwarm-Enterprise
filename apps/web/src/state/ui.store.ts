import { create } from "zustand";
import { ENTITY_TYPE, type EntityType } from "@/enums/scene.enum";
import { FOCUS_SOURCE, LENS, VIEW_MODE, type FocusSource, type Lens, type ViewMode } from "@/enums/ui.enum";

type UiStore = {
  selectedEntityId: string | null;
  /** What the selected id names: a product (SKU), a shelf, or a piece of equipment. */
  selectedEntityType: EntityType | null;
  /** Who made the current selection: the user, or the agent (`focusEntity`); null when nothing is selected. */
  focusSource: FocusSource | null;
  /** Why the agent focused the current selection, shown as a caption; null for the user's own. */
  focusReason: string | null;
  /** Counts `focusEntity` calls, so the camera flies again to an entity that is already selected. */
  focusSeq: number;
  /** Whether the camera follows what the agent works on. On by default. */
  followAgent: boolean;
  /** True while the user drags the camera. */
  userDragging: boolean;
  /** When the user last moved the camera or made a selection, in ms since the epoch; 0 before. */
  userActiveAt: number;
  viewMode: ViewMode;
  /** When the view mode last changed, in ms since the epoch; 0 before any change. */
  viewChangedAt: number;
  /** Operations, revenue, or promotions: picks the panel's content. */
  lens: Lens;
  /** The product whose details dialog is open, or null. */
  detailsSku: string | null;
  /** The promotion the Promotions lens should scroll to and flash, until it has. */
  focusedPromotionId: string | null;
  /** Selects an entity, a product unless told otherwise; `null` clears the selection. */
  select: (entityId: string | null, entityType?: EntityType) => void;
  /** The agent selects an entity and flies the camera to it, captioned with `reason`. */
  focusEntity: (entityId: string, entityType: EntityType, reason: string) => void;
  setFollowAgent: (followAgent: boolean) => void;
  /** Records that the user started (`true`) or stopped (`false`) dragging the camera. */
  markUserActivity: (dragging: boolean) => void;
  setViewMode: (mode: ViewMode) => void;
  setLens: (lens: Lens) => void;
  /** Opens the details dialog of a product; `null` closes it. */
  showDetails: (sku: string | null) => void;
  /** Switches to the Promotions lens on one promotion; `null` once it has been shown. */
  focusPromotion: (promotionId: string | null) => void;
};

export const useUiStore = create<UiStore>()((set) => ({
  selectedEntityId: null,
  selectedEntityType: null,
  focusSource: null,
  focusReason: null,
  focusSeq: 0,
  followAgent: true,
  userDragging: false,
  userActiveAt: 0,
  viewMode: VIEW_MODE.Live,
  viewChangedAt: 0,
  lens: LENS.Operations,
  detailsSku: null,
  focusedPromotionId: null,
  select: (selectedEntityId, entityType = ENTITY_TYPE.Product) =>
    set({
      selectedEntityId,
      selectedEntityType: selectedEntityId ? entityType : null,
      focusSource: selectedEntityId ? FOCUS_SOURCE.User : null,
      focusReason: null,
      userActiveAt: Date.now(),
    }),
  focusEntity: (selectedEntityId, selectedEntityType, focusReason) =>
    set((ui) => ({
      selectedEntityId,
      selectedEntityType,
      focusSource: FOCUS_SOURCE.Agent,
      focusReason,
      focusSeq: ui.focusSeq + 1,
    })),
  setFollowAgent: (followAgent) => set({ followAgent }),
  markUserActivity: (userDragging) => set({ userDragging, userActiveAt: Date.now() }),
  setViewMode: (viewMode) =>
    set((ui) => (ui.viewMode === viewMode ? {} : { viewMode, viewChangedAt: Date.now() })),
  setLens: (lens) => set({ lens }),
  showDetails: (detailsSku) => set({ detailsSku }),
  focusPromotion: (focusedPromotionId) =>
    set(focusedPromotionId ? { focusedPromotionId, lens: LENS.Promotions } : { focusedPromotionId }),
}));

/** True while `entityId` is the selected entity of `entityType`. */
export function isSelected(state: Pick<UiStore, "selectedEntityId" | "selectedEntityType">, entityId: string, entityType: EntityType) {
  return state.selectedEntityId === entityId && state.selectedEntityType === entityType;
}

/** The selected product's SKU, or null when nothing or a fixture is selected. */
export function selectedProductId(state: Pick<UiStore, "selectedEntityId" | "selectedEntityType">) {
  return state.selectedEntityType === ENTITY_TYPE.Product ? state.selectedEntityId : null;
}
