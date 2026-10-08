/** Window a revenue report covers. */
export const REVENUE_PERIOD = {
  Today: "today",
  Week: "7d",
  Month: "30d",
} as const;
export type RevenuePeriod = (typeof REVENUE_PERIOD)[keyof typeof REVENUE_PERIOD];
export const REVENUE_PERIODS: readonly RevenuePeriod[] = Object.values(REVENUE_PERIOD);

/** Width of one bar in the revenue chart. */
export const BUCKET_SIZE = {
  Hour: "hour",
  Day: "day",
} as const;
export type BucketSize = (typeof BUCKET_SIZE)[keyof typeof BUCKET_SIZE];

/** Where a promotion is in its life cycle. Price changes go through human review first. */
export const PROMOTION_STATUS = {
  Active: "active",
  Scheduled: "scheduled",
  PendingReview: "pending_review",
  Draft: "draft",
  Ended: "ended",
} as const;
export type PromotionStatus = (typeof PROMOTION_STATUS)[keyof typeof PROMOTION_STATUS];
export const PROMOTION_STATUSES: readonly PromotionStatus[] = Object.values(PROMOTION_STATUS);

/** How a promotion discounts. */
export const PROMOTION_KIND = {
  PercentOff: "percent_off",
  AmountOff: "amount_off",
  BuyXGetY: "buy_x_get_y",
  Bundle: "bundle",
} as const;
export type PromotionKind = (typeof PROMOTION_KIND)[keyof typeof PROMOTION_KIND];
