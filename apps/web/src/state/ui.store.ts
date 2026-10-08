import { create } from "zustand";
import { LENS, VIEW_MODE, type Lens, type ViewMode } from "@/enums/ui.enum";

type UiStore = {
  selectedEntityId: string | null;
  viewMode: ViewMode;
  /** Operations, revenue, or promotions: picks the panel's content. */
  lens: Lens;
  select: (entityId: string | null) => void;
  setViewMode: (mode: ViewMode) => void;
  setLens: (lens: Lens) => void;
};

export const useUiStore = create<UiStore>()((set) => ({
  selectedEntityId: null,
  viewMode: VIEW_MODE.Live,
  lens: LENS.Operations,
  select: (selectedEntityId) => set({ selectedEntityId }),
  setViewMode: (viewMode) => set({ viewMode }),
  setLens: (lens) => set({ lens }),
}));
