import { create } from "zustand";
import type { AiImpact } from "@/core/twin/aiImpact";

type ImpactStore = {
  /** The impact of the last executed approval, or null when it accepted no candidate. */
  last: AiImpact | null;
  /** The simulation whose impact toast has been shown, so it shows once. */
  toastShownFor: string | null;
  /** Whether the comparison of the impact's candidates is open. */
  comparing: boolean;
  record: (impact: AiImpact | null) => void;
  markToastShown: (simulationId: string) => void;
  setComparing: (comparing: boolean) => void;
};

/**
 * The AI Impact of the last executed approval. It outlives the run, whose candidates leave
 * `twin.store` once it closes, so the card can show when the agent's run reaches VERIFY.
 */
export const useImpactStore = create<ImpactStore>()((set) => ({
  last: null,
  toastShownFor: null,
  comparing: false,
  record: (last) => set({ last, comparing: false }),
  markToastShown: (toastShownFor) => set({ toastShownFor }),
  setComparing: (comparing) => set({ comparing }),
}));
