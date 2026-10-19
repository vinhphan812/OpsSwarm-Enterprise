import { CURRENCY } from "@/constants/i18n.constant";
import { BUCKET_SIZE, REVENUE_GRAIN, REVENUE_GRAINS, type RevenuePeriod } from "@/enums/commerce.enum";
import type { RevenueBucket, RevenueResponse, RevenueResponseBucket, RevenueSummary } from "@/types/revenue.type";
import type { RevenueQuery } from "./revenueWindow";

/** A served payload breaks the contract at `field`, so none of it is shown. */
export class ContractError extends Error {
  readonly field: string;

  constructor(field: string) {
    super(`The response breaks the contract at "${field}".`);
    this.name = "ContractError";
    this.field = field;
  }
}

type Fields = Record<string, unknown>;

const isObject = (value: unknown): value is Fields => typeof value === "object" && value !== null && !Array.isArray(value);
const isText = (value: unknown): value is string => typeof value === "string" && value.trim() !== "";
const isAmount = (value: unknown): value is number => typeof value === "number" && Number.isFinite(value) && value >= 0;
const isCount = (value: unknown): value is number => Number.isInteger(value) && (value as number) >= 0;
const isInstant = (value: unknown): value is string => isText(value) && !Number.isNaN(Date.parse(value));

function parseBucket(raw: unknown, at: string): RevenueResponseBucket {
  if (!isObject(raw) || !isInstant(raw.timestamp) || !isAmount(raw.revenue) || !isCount(raw.transactions) || !isCount(raw.items_sold)) {
    throw new ContractError(at);
  }
  return { timestamp: raw.timestamp, revenue: raw.revenue, transactions: raw.transactions, items_sold: raw.items_sold };
}

/** Checks a `GET /revenue` payload against apps/api's `RevenueResponse`. Anything off throws `ContractError`. */
export function parseRevenueResponse(raw: unknown): RevenueResponse {
  if (!isObject(raw)) throw new ContractError("response");
  if (!isText(raw.store_id)) throw new ContractError("store_id");
  if (!REVENUE_GRAINS.includes(raw.period as never)) throw new ContractError("period");
  for (const field of ["start", "end"] as const) if (!isInstant(raw[field])) throw new ContractError(field);
  for (const field of ["total_revenue", "avg_transaction_value"] as const) if (!isAmount(raw[field])) throw new ContractError(field);
  for (const field of ["total_transactions", "total_items_sold"] as const) if (!isCount(raw[field])) throw new ContractError(field);
  if (!isText(raw.currency)) throw new ContractError("currency");
  if (!Array.isArray(raw.buckets)) throw new ContractError("buckets");
  return {
    store_id: raw.store_id,
    period: raw.period as RevenueResponse["period"],
    start: raw.start as string,
    end: raw.end as string,
    total_revenue: raw.total_revenue as number,
    total_transactions: raw.total_transactions as number,
    total_items_sold: raw.total_items_sold as number,
    avg_transaction_value: raw.avg_transaction_value as number,
    currency: raw.currency,
    buckets: raw.buckets.map((bucket, index) => parseBucket(bucket, `buckets[${index}]`)),
  };
}

const HOUR_MS = 3_600_000;
const DAY_MS = 24 * HOUR_MS;

/** The UTC hour or day `instant` falls in, as apps/api cuts its buckets (`TIMESTAMP_TRUNC`). */
function floorTo(instant: number, stepMs: number): number {
  return Math.floor(instant / stepMs) * stepMs;
}

/**
 * Every bucket of the window, oldest first: the ones apps/api served, and 0 for the hours or
 * days it served none, which had no sales (it groups the sales it read). A served bucket off
 * that grid breaks the contract.
 */
function fillBuckets(response: RevenueResponse, stepMs: number): RevenueBucket[] {
  const served = new Map<number, number>();
  for (const [index, bucket] of response.buckets.entries()) {
    const at = Date.parse(bucket.timestamp);
    if (at !== floorTo(at, stepMs)) throw new ContractError(`buckets[${index}].timestamp`);
    served.set(at, (served.get(at) ?? 0) + bucket.revenue);
  }
  const first = floorTo(Date.parse(response.start), stepMs);
  const last = floorTo(Date.parse(response.end), stepMs);
  const buckets: RevenueBucket[] = [];
  for (let at = first; at <= last; at += stepMs) {
    buckets.push({ start: new Date(at).toISOString(), revenue: served.get(at) ?? 0 });
    served.delete(at);
  }
  if (served.size) throw new ContractError("buckets");
  return buckets;
}

/**
 * `GET /revenue` as the lens window `period` shows it. Only what apps/api served: margin, the
 * window before, lost sales, categories and SKU rankings are not served, so they are null, not 0.
 * It must answer the `query` sent (same grain) for the store, in `CURRENCY`; otherwise it throws.
 */
export function toRevenueSummary(response: RevenueResponse, period: RevenuePeriod, query: RevenueQuery): RevenueSummary {
  if (response.period !== query.period) throw new ContractError("period");
  if (response.currency !== CURRENCY) throw new ContractError("currency");
  const hourly = query.period === REVENUE_GRAIN.Hourly;
  return {
    store_id: response.store_id,
    period,
    start: response.start,
    end: response.end,
    currency: response.currency,
    revenue: response.total_revenue,
    transactions: response.total_transactions,
    average_basket: response.avg_transaction_value,
    items_sold: response.total_items_sold,
    margin_rate: null,
    lost_to_stockout: null,
    previous: null,
    bucket_size: hourly ? BUCKET_SIZE.Hour : BUCKET_SIZE.Day,
    buckets: fillBuckets(response, hourly ? HOUR_MS : DAY_MS),
    categories: null,
    top_skus: null,
    slow_skus: null,
  };
}
