import type { TwinSource } from "@/core/api/sources/TwinSource";
import type { StoreResponse } from "@/types/twin.type";
import { parseStoreState, type ProductIssue } from "@/core/api/validate";
import { isNewerVersion } from "@/core/api/version";
import { TWIN_STATUS, type TwinStatus } from "@/enums/twin.enum";

type ConnectionEvents = {
  /** A state newer than any delivered before, without the products that broke the contract. */
  onState: (state: StoreResponse, issues: ProductIssue[]) => void;
  /** Loading until the first state, then ready; error when the first load fails. */
  onStatus: (status: TwinStatus, error?: unknown) => void;
  /** The live feed dropped or sent an unreadable state after the first one; the last state stays on screen. */
  onFeedError: (error: unknown) => void;
  /** A readable state arrived again after `onFeedError`. */
  onFeedRestored?: () => void;
};

/**
 * Loads the snapshot and follows updates. A pushed update is newer than a snapshot
 * still in flight, and a state is only delivered when its version is newer than the
 * last one, so late or replayed messages never roll the scene back. Every payload is
 * checked against the contract first; one that is not a store state counts as a
 * failed load. Each outage is reported once, and the next readable state ends it,
 * so a polling source neither repeats errors nor stays stale after it recovers.
 * Returns the cleanup; after it runs nothing more is delivered.
 */
export function connectTwin(source: TwinSource, events: ConnectionEvents): () => void {
  let active = true;
  let lastVersion: string | null = null;
  let down = false;

  const fail = (error: unknown) => {
    if (!active || down) return;
    down = true;
    if (lastVersion === null) events.onStatus(TWIN_STATUS.Error, error);
    else events.onFeedError(error);
  };

  const deliver = (payload: StoreResponse) => {
    if (!active) return;
    let parsed: ReturnType<typeof parseStoreState>;
    try {
      parsed = parseStoreState(payload);
    } catch (error) {
      fail(error);
      return;
    }
    const { state, issues } = parsed;
    if (down) {
      down = false;
      if (lastVersion !== null) events.onFeedRestored?.();
    }
    if (!isNewerVersion(state.context_version, lastVersion)) return;
    const first = lastVersion === null;
    lastVersion = state.context_version;
    events.onState(state, issues);
    if (first) events.onStatus(TWIN_STATUS.Ready);
  };

  events.onStatus(TWIN_STATUS.Loading);
  source
    .snapshot()
    .then(deliver)
    .catch((error: unknown) => {
      // An update may already have arrived; then the twin is reachable after all.
      if (lastVersion === null) fail(error);
    });

  const unsubscribe = source.subscribe(deliver, fail);

  return () => {
    active = false;
    unsubscribe();
  };
}
