import { create } from "zustand";

/** Structured error entry for persistent error visibility. */
export interface ErrorLogEntry {
  id: string;
  timestamp: string;
  source: string;
  message: string;
  details?: string;
  recoverable: boolean;
}

type ErrorLogState = {
  entries: ErrorLogEntry[];
  add: (entry: Omit<ErrorLogEntry, "id" | "timestamp">) => void;
  clear: () => void;
  remove: (id: string) => void;
};

const generateId = () => crypto.randomUUID();

/**
 * Persistent error log store.
 * Captures structured errors from API calls, polling, and other operations
 * for visibility in the Operations panel.
 */
export const useErrorLogStore = create<ErrorLogState>((set) => ({
  entries: [],

  add: (entry) =>
    set((state) => ({
      entries: [
        {
          ...entry,
          id: generateId(),
          timestamp: new Date().toISOString(),
        },
        ...state.entries,
      ].slice(0, 100), // Keep last 100 errors
    })),

  clear: () => set({ entries: [] }),

  remove: (id) =>
    set((state) => ({
      entries: state.entries.filter((e) => e.id !== id),
    })),
}));
