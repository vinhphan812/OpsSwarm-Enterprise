import { create } from "zustand";
import type { ReviewResult } from "@/types/simulation.type";

/** An approval the guard answered, with the Live version its proposal was built on. */
export type GuardReview = {
  result: ReviewResult;
  base_context_version: string;
};

type GuardStore = {
  last: GuardReview | null;
  record: (review: GuardReview) => void;
  clear: () => void;
};

/**
 * The guard's last answer. It outlives the run it was about, so after a commit the Live view
 * still shows why the store changed, and after a refusal why it did not.
 */
export const useGuardStore = create<GuardStore>()((set) => ({
  last: null,
  record: (last) => set({ last }),
  clear: () => set({ last: null }),
}));
