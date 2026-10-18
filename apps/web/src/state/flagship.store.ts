import { create } from "zustand";
import type { FlagshipStatus } from "@/types/api.type";

/**
 * Latest snapshot of `GET /flagship/status`, refreshed by the polling hook.
 * `status` is null on first render; `error` carries the last read failure
 * for the panel to surface. The store never invents a phase: an empty
 * `status` is rendered as "no flagship run yet".
 */
type FlagshipStore = {
  status: FlagshipStatus | null;
  error: string | null;
  setStatus: (status: FlagshipStatus | null, error: string | null) => void;
  /** Reset to IDLE so a new run shows its own phases from scratch. */
  clear: () => void;
};

export const useFlagshipStore = create<FlagshipStore>((set) => ({
  status: null,
  error: null,
  setStatus: (status, error) => set({ status, error }),
  clear: () => set({ status: null, error: null }),
}));