import { create } from "zustand";
import type { ActivityEntry, ControlStage } from "@/core/api/types";

type RunStore = {
  activity: ActivityEntry[];
  stage: ControlStage | null;
  append: (entry: ActivityEntry) => void;
  reset: () => void;
};

export const useRunStore = create<RunStore>()((set) => ({
  activity: [],
  stage: null,
  append: (entry) =>
    set((state) =>
      state.activity.some((existing) => existing.id === entry.id)
        ? state
        : { activity: [...state.activity, entry], stage: entry.stage },
    ),
  reset: () => set({ activity: [], stage: null }),
}));
