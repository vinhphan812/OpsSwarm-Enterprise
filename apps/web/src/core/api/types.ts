import type { BucketSize, PromotionKind, PromotionStatus, RevenuePeriod } from "@/enums/commerce.enum";

export type HealthResponse = {
  status: "ok" | "degraded";
  service: "retailtwin-api";
  environment: string;
  store_id: string;
  fixture_loaded: boolean;
};

export type ProductInventory = {
  store_id: string;
  sku: string;
  shelf_id: string;
  slot_id: string;
  facings: number;
  shelf_quantity: number;
  backroom_quantity: number;
  version: number;
};

export type StoreResponse = {
  store_id: string;
  context_version: string;
  version: string;
  products: ProductInventory[];
};

export type RetailTwinClient = {
  health: () => Promise<HealthResponse>;
  store: () => Promise<StoreResponse>;
  inventory: (sku: string) => Promise<ProductInventory>;
};

export type ControlStage =
  | "OBSERVE"
  | "DETECT"
  | "INVESTIGATE"
  | "PLAN"
  | "SIMULATE"
  | "GUARD"
  | "ACT"
  | "VERIFY";

export type GuardVerdict = "ALLOW" | "REFRESH_REQUIRED" | "DENY";

/** One line of the Agent Activity timeline. A summary, never model reasoning. */
export type ActivityEntry = {
  id: string;
  ts: string;
  stage: ControlStage;
  summary: string;
  correlation_id?: string;
  decision_id?: string;
  sku?: string;
};

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
