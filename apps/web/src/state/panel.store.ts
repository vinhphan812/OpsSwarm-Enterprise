import { create } from "zustand";
import { createJSONStorage, persist } from "zustand/middleware";

type PanelStore = {
  open: boolean;
  setOpen: (open: boolean) => void;
};

/** Whether the Agent Activity panel is open, remembered per browser. A viewer convenience only. */
export const usePanelStore = create<PanelStore>()(
  persist(
    (set) => ({
      open: true,
      setOpen: (open) => set({ open }),
    }),
    {
      name: "retailtwin.panel",
      storage: createJSONStorage(() => localStorage),
      // Older versions also stored a width; only `open` is read back.
      merge: (stored, current) => ({
        ...current,
        open: (stored as Partial<PanelStore> | undefined)?.open ?? current.open,
      }),
    },
  ),
);
