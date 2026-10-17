import { create } from "zustand";
import type { AiChanges } from "@/core/twin/aiChanges";
import type { AiImpact } from "@/core/twin/aiImpact";

/** What an executed approval changed in the store: Live before against the committed proposal. */
export type ExecutedChanges = { simulation_id: string; changes: AiChanges };

type ImpactStore = {
  /** The impact of the last executed approval, or null when it accepted no candidate. */
  last: AiImpact | null;
  /** The AI CHANGES of the last executed approval, or null before one. */
  executed: ExecutedChanges | null;
  /** The simulation whose impact toast has been shown, so it shows once. */
  toastShownFor: string | null;
  /** Whether the comparison of the impact's candidates is open. */
  comparing: boolean;
  record: (impact: AiImpact | null) => void;
  recordExecuted: (executed: ExecutedChanges | null) => void;
  markToastShown: (simulationId: string) => void;
  setComparing: (comparing: boolean) => void;
};

/**
 * The AI Impact and AI CHANGES of the last executed approval. They outlive the run, whose
 * candidates and proposal leave `twin.store` once it closes, so the run's card can still
 * show them: the changes under ACT, the impact once the run reaches VERIFY.
 */
export const useImpactStore = create<ImpactStore>()((set) => ({
  last: null,
  executed: null,
  toastShownFor: null,
  comparing: false,
  record: (last) => set({ last, comparing: false }),
  recordExecuted: (executed) => set({ executed }),
  markToastShown: (toastShownFor) => set({ toastShownFor }),
  setComparing: (comparing) => set({ comparing }),
}));
