import { useEffect, useMemo, useState } from "react";
import i18n from "@/i18n";
import { defaultClient } from "@/core/api/client";
import { notify } from "@/core/notify";
import type { PromotionsSummary } from "@/types/promotion.type";
import type { RevenueSummary } from "@/types/revenue.type";
import type { RetailTwinClient } from "@/types/api.type";
import type { RevenuePeriod } from "@/enums/commerce.enum";
import { emptyPromotions, emptyRevenue } from "@/fixtures/commerceFixture";
import { storeFixture } from "@/fixtures/storeFixture";
import { useTwinStore } from "@/state/twin.store";

/** The store the live twin reports, or the fixture's until it loads. */
function useStoreId() {
  return useTwinStore((state) => state.live?.store_id) ?? storeFixture.storeId;
}

type ReadCache = { reads: Map<string, Promise<unknown>>; results: Map<string, unknown> };
const caches = new WeakMap<RetailTwinClient, ReadCache>();

function cacheOf(client: RetailTwinClient): ReadCache {
  let cache = caches.get(client);
  if (!cache) {
    cache = { reads: new Map(), results: new Map() };
    caches.set(client, cache);
  }
  return cache;
}

/**
 * One read per key, shared by every mount, so switching lenses does not call the API
 * again. A failed read is dropped, toasts once, and is retried on the next mount.
 */
function useCachedRead<T>(client: RetailTwinClient, key: string, read: () => Promise<T>, placeholder: T): T {
  const { reads, results } = cacheOf(client);
  const [value, setValue] = useState(() => (results.get(key) as T | undefined) ?? placeholder);

  useEffect(() => {
    let cancelled = false;
    let pending = reads.get(key) as Promise<T> | undefined;
    if (!pending) {
      pending = read().then(
        (result) => {
          results.set(key, result);
          return result;
        },
        (error: unknown) => {
          reads.delete(key);
          notify.error(i18n.t("commerce.loadFailed"), error);
          throw error;
        },
      );
      reads.set(key, pending);
    }
    setValue((results.get(key) as T | undefined) ?? placeholder);
    pending.then(
      (result) => !cancelled && setValue(result),
      () => {},
    );
    return () => {
      cancelled = true;
    };
    // `read` and `placeholder` follow from `client` and `key`.
  }, [client, key]);

  return value;
}

/** `GET /revenue` for one window, read when the Revenue lens opens. All zeros until it lands. */
export function useRevenue(period: RevenuePeriod, client: RetailTwinClient = defaultClient): RevenueSummary {
  const storeId = useStoreId();
  const placeholder = useMemo(() => emptyRevenue(storeId, period), [storeId, period]);
  return useCachedRead(client, `revenue:${storeId}:${period}`, () => client.revenue(period), placeholder);
}

/** `GET /promotions`, read when the Promotions lens opens. Read only; empty until it lands. */
export function usePromotions(client: RetailTwinClient = defaultClient): PromotionsSummary {
  const storeId = useStoreId();
  const placeholder = useMemo(() => emptyPromotions(storeId), [storeId]);
  return useCachedRead(client, `promotions:${storeId}`, () => client.promotions(), placeholder);
}
