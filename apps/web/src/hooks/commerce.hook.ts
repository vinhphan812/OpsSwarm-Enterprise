import { useEffect, useMemo, useState } from "react";
import i18n from "@/i18n";
import { defaultClient } from "@/core/api/client";
import { isDemoMode } from "@/core/twin/demoMode";
import { demoClient } from "@/fixtures/demo/commerce";
import { notify } from "@/core/notify";
import type { PromotionsSummary } from "@/types/promotion.type";
import type { RevenueSummary } from "@/types/revenue.type";
import type { RetailTwinClient } from "@/types/api.type";
import type { RevenuePeriod } from "@/enums/commerce.enum";
import { emptyPromotions, emptyRevenue } from "@/fixtures/commerceFixture";
import { storeFixture } from "@/fixtures/storeFixture";
import { useTwinStore } from "@/state/twin.store";

/**
 * The client the lenses read: the demo data under `?twin=demo`, otherwise apps/api.
 * A failed read never falls back to demo data; the lens keeps its empty report.
 */
function commerceClient(): RetailTwinClient {
  return isDemoMode() ? demoClient : defaultClient;
}

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
 * Without a client nothing is read and the placeholder stays.
 */
function useCachedRead<T>(
  client: RetailTwinClient | undefined,
  key: string,
  read: (client: RetailTwinClient) => Promise<T>,
  placeholder: T,
): T {
  const [value, setValue] = useState(() => (client && (cacheOf(client).results.get(key) as T | undefined)) ?? placeholder);

  useEffect(() => {
    if (!client) {
      setValue(placeholder);
      return;
    }
    const { reads, results } = cacheOf(client);
    let cancelled = false;
    let pending = reads.get(key) as Promise<T> | undefined;
    if (!pending) {
      pending = read(client).then(
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
export function useRevenue(
  period: RevenuePeriod,
  client: RetailTwinClient | undefined = commerceClient(),
): RevenueSummary {
  const storeId = useStoreId();
  const placeholder = useMemo(() => emptyRevenue(storeId, period), [storeId, period]);
  return useCachedRead(client, `revenue:${storeId}:${period}`, (api) => api.revenue(period), placeholder);
}

/** `GET /promotions`, read when the Promotions lens opens. Read only; empty until it lands. */
export function usePromotions(client: RetailTwinClient | undefined = commerceClient()): PromotionsSummary {
  const storeId = useStoreId();
  const placeholder = useMemo(() => emptyPromotions(storeId), [storeId]);
  return useCachedRead(client, `promotions:${storeId}`, (api) => api.promotions(), placeholder);
}
