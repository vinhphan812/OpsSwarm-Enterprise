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
  margin_rate?: number;
  avgBasket?: number;
  units?: number;
};

/** Single revenue bucket in API response. */
export type RevenueResponseBucket = {
  timestamp?: string;
  revenue: number;
  transactions?: number;
  items_sold?: number;
  start?: string;
};

/** API response for revenue endpoint. */
export type RevenueResponse = {
  store_id: string;
  period: string;
  currency: string;
  start: string;
  end: string;
  total_revenue: number;
  total_transactions: number;
  avg_transaction_value: number;
  total_items_sold: number;
  buckets: RevenueResponseBucket[];
};

/**
 * Response of `GET /revenue?period=today|7d|30d`. Money is in the store's currency.
 * TODO(BE): apps/api does not serve this route yet.
 */
export type RevenueSummary = RevenueTotals & {
  store_id: string;
  period: RevenuePeriod;
  start: string;
  end: string;
  currency: string;
  items_sold: number;
  /** Estimated sales lost while a product was out of stock on the shelf. */
  lost_to_stockout?: number;
  previous?: RevenueTotals;
  bucket_size: BucketSize;
  buckets: RevenueBucket[];
  categories?: CategoryRevenue[];
  top_skus?: SkuRevenue[];
  /** Low sellers that still hold shelf space. */
  slow_skus?: SkuRevenue[];
};
