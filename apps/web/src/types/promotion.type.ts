import type { PromotionKind, PromotionStatus } from "@/enums/commerce.enum";

export type Promotion = {
  id: string;
  name: string;
  status: PromotionStatus;
  kind: PromotionKind;
  /** Percent (0..1) for `percent_off`, money for `amount_off`, free units for `buy_x_get_y`. */
  value: number;
  starts_at: string;
  ends_at: string;
  skus: string[];
  revenue: number;
  /** Revenue above the baseline forecast while the promotion ran. */
  incremental_revenue: number;
  discount_cost: number;
};

/**
 * Response of `GET /promotions`: the store's promotions and their totals. Read only; a price
 * change goes through human review in the agent loop, never through this route.
 * TODO(BE): apps/api does not serve this route yet.
 */
export type PromotionsSummary = {
  store_id: string;
  revenue: number;
  incremental_revenue: number;
  discount_cost: number;
  promotions: Promotion[];
};
