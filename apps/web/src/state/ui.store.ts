import { create } from "zustand";
import { ENTITY_TYPE, type EntityType } from "@/enums/scene.enum";
import { LENS, VIEW_MODE, type Lens, type ViewMode } from "@/enums/ui.enum";

type UiStore = {
  selectedEntityId: string | null;
  /** What the selected id names: a product (SKU), a shelf, or a piece of equipment. */
  selectedEntityType: EntityType | null;
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
  viewMode: VIEW_MODE.Live,
  viewChangedAt: 0,
  lens: LENS.Operations,
  detailsSku: null,
  focusedPromotionId: null,
  select: (selectedEntityId, entityType = ENTITY_TYPE.Product) =>
    set({ selectedEntityId, selectedEntityType: selectedEntityId ? entityType : null }),
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
