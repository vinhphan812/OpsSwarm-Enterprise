import { useMemo } from "react";
import type { PromotionsSummary, RevenueSummary } from "@/core/api/types";
import type { RevenuePeriod } from "@/enums/commerce.enum";
import { emptyPromotions, emptyRevenue } from "@/fixtures/commerceFixture";
import { storeFixture } from "@/fixtures/storeFixture";
import { useTwinStore } from "@/state/twin.store";

/** The store the live twin reports, or the fixture's until it loads. */
function useStoreId() {
  return useTwinStore((state) => state.live?.store_id) ?? storeFixture.storeId;
}

/**
 * Sales figures of one window. Sales are not wired to an API yet, so every figure is 0;
 * swap the body for a request when `GET /sales/summary` exists.
 */
export function useRevenue(period: RevenuePeriod): RevenueSummary {
  const storeId = useStoreId();
  return useMemo(() => emptyRevenue(storeId, period), [storeId, period]);
}

/** Promotions of the store. Read-only and empty until `GET /promotions` exists. */
export function usePromotions(): PromotionsSummary {
  const storeId = useStoreId();
  return useMemo(() => emptyPromotions(storeId), [storeId]);
}
