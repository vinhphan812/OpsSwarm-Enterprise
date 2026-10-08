import { create } from "zustand";
import { createJSONStorage, persist } from "zustand/middleware";
import { PANEL_WIDTH } from "@/constants/app.constant";

type PanelStore = {
  open: boolean;
  width: number;
  setOpen: (open: boolean) => void;
  /** Clamped to PANEL_WIDTH.min..max. */
  setWidth: (width: number) => void;
};

const clampWidth = (width: number) => Math.round(Math.min(PANEL_WIDTH.max, Math.max(PANEL_WIDTH.min, width)));

/** Agent Activity panel layout, remembered per browser. A viewer convenience only. */
export const usePanelStore = create<PanelStore>()(
  persist(
    (set) => ({
      open: true,
      width: PANEL_WIDTH.default,
      setOpen: (open) => set({ open }),
      setWidth: (width) => set({ width: clampWidth(width) }),
    }),
    {
      name: "retailtwin.panel",
      storage: createJSONStorage(() => localStorage),
      // A stored width from an older range is pulled back inside the current one.
      merge: (stored, current) => {
        const saved = (stored ?? {}) as Partial<PanelStore>;
        return {
          ...current,
          open: saved.open ?? current.open,
          width: clampWidth(saved.width ?? current.width),
        };
      },
    },
  ),
);
