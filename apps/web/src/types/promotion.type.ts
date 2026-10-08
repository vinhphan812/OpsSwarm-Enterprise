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

export type PromotionsSummary = {
  store_id: string;
  revenue: number;
  incremental_revenue: number;
  discount_cost: number;
  promotions: Promotion[];
};
