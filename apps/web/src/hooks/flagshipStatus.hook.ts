import { useEffect } from "react";
import type { FlagshipStatus } from "@/types/api.type";
import { defaultClient } from "@/core/api/client";
import { useFlagshipStore } from "@/state/flagship.store";

const POLL_MS = 2000;

/**
 * Polls `GET /flagship/status` every 2 seconds and writes the result into
 * `useFlagshipStore`. The store starts empty (`phase=IDLE`); each tick overwrites
 * it with the singleton's current phase, guard verdict, timeline, etc. so the
 * Agent Activity panel can render whichever state the controller is in.
 *
 * A failed read keeps the last known status and bumps `error`. The poll
 * stops on unmount; tab visibility is not gated (matches `apiSource`).
 * Off (`enabled` false) on a `?twin=` dev twin and in the demo, which read no apps/api.
 */
export function useFlagshipStatus(enabled = true): void {
  const setStatus = useFlagshipStore((state) => state.setStatus);

  useEffect(() => {
    if (!enabled) return;
    let cancelled = false;
    let timer: ReturnType<typeof setTimeout> | null = null;

    const tick = async (): Promise<void> => {
      if (cancelled) return;
      try {
        const status = await defaultClient.flagshipStatus();
        if (cancelled) return;
        setStatus(status as FlagshipStatus, null);
      } catch (error) {
        if (cancelled) return;
        // Keeps the last status it read: the section says the poll failed, and shows no other run.
        setStatus(useFlagshipStore.getState().status, error instanceof Error ? error.message : String(error));
      }
      if (!cancelled) timer = setTimeout(tick, POLL_MS);
    };

    void tick();
    return () => {
      cancelled = true;
      if (timer) clearTimeout(timer);
    };
  }, [enabled, setStatus]);
}