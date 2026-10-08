import { defaultClient } from "@/core/api/client";
import { TWIN_POLL_MAX_MS, TWIN_POLL_MS } from "@/constants/twin.constant";
import type { RetailTwinClient } from "@/types/api.type";
import type { TwinSource } from "./TwinSource";

/** True while the browser tab is in the background; there is no tab outside the browser. */
const tabHidden = () => typeof document !== "undefined" && document.hidden;

/**
 * Live Twin state from `GET /store` on apps/api. The API has no push channel yet, so
 * the feed polls; connectTwin drops a state whose context version is not newer.
 * A failed read doubles the wait before the next one, up to `maxIntervalMs`, and a
 * good read brings it back to `intervalMs`. Nothing is read while the tab is hidden.
 */
export function createApiSource(
  client: RetailTwinClient = defaultClient,
  intervalMs = TWIN_POLL_MS,
  maxIntervalMs = TWIN_POLL_MAX_MS,
): TwinSource {
  return {
    snapshot: () => client.store(),
    subscribe: (onState, onError) => {
      let active = true;
      let delay = intervalMs;
      let timer: ReturnType<typeof setTimeout>;

      const poll = async () => {
        if (!tabHidden()) {
          try {
            const state = await client.store();
            if (!active) return;
            delay = intervalMs;
            onState(state);
          } catch (error) {
            if (!active) return;
            delay = Math.min(delay * 2, maxIntervalMs);
            onError?.(error);
          }
        }
        if (active) timer = setTimeout(poll, delay);
      };

      timer = setTimeout(poll, delay);
      return () => {
        active = false;
        clearTimeout(timer);
      };
    },
  };
}
