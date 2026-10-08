import type { BucketSize, RevenuePeriod } from "@/enums/commerce.enum";

/** Revenue of one chart bar: an hour of today, or a day of a longer window. */
export type RevenueBucket = {
  /** ISO start of the bucket. */
  start: string;
  revenue: number;
};

export type SkuRevenue = {
  sku: string;
  name: string;
  revenue: number;
  units: number;
  facings: number;
};

export type CategoryRevenue = {
  /** A `scene.stock` category key, such as `packaged`. */
  category: string;
  revenue: number;
};

/** Headline figures of a window; `previous` holds the window before it, for the change badges. */
export type RevenueTotals = {
  revenue: number;
  transactions: number;
  average_basket: number;
  /** 0..1 */
  margin_rate: number;
};

export type RevenueSummary = RevenueTotals & {
  store_id: string;
  period: RevenuePeriod;
  /** Estimated sales lost while a product was out of stock on the shelf. */
  lost_to_stockout: number;
  previous: RevenueTotals;
  bucket_size: BucketSize;
  buckets: RevenueBucket[];
  categories: CategoryRevenue[];
  top_skus: SkuRevenue[];
  /** Low sellers that still hold shelf space. */
  slow_skus: SkuRevenue[];
};
