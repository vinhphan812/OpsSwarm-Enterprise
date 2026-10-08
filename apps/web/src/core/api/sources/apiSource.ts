import { defaultClient } from "@/core/api/client";
import { TWIN_POLL_MS } from "@/constants/twin.constant";
import type { RetailTwinClient } from "@/types/api.type";
import type { TwinSource } from "./TwinSource";

/**
 * Live Twin state from `GET /store` on apps/api. The API has no push channel yet, so
 * the feed polls; connectTwin drops a state whose context version is not newer.
 */
export function createApiSource(client: RetailTwinClient = defaultClient, intervalMs = TWIN_POLL_MS): TwinSource {
  return {
    snapshot: () => client.store(),
    subscribe: (onState, onError) => {
      let active = true;
      const timer = setInterval(() => {
        client.store().then(
          (state) => active && onState(state),
          (error: unknown) => active && onError?.(error),
        );
      }, intervalMs);
      return () => {
        active = false;
        clearInterval(timer);
      };
    },
  };
}
