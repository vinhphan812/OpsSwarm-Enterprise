import { mulberry32, pick } from "@/core/utils/random";
import { CHECKOUT_STATUS, PAYMENT_METHOD } from "@/enums/checkout.enum";
import type { Cashier, CheckoutLine, CheckoutSummary, CheckoutTransaction } from "@/types/checkout.type";

/**
 * Demo data for `?twin=demo` (development builds only), never Live Twin truth.
 * Checkout lanes and today's sales, in the proposed checkout API shapes. Each lane's
 * sales are generated from a fixed price list of the demo store's SKUs, the same on
 * every load, and the lane's figures (revenue, items, last sale) add them up, so the
 * card, the payments list, and each receipt always agree.
 */

/** A lane as it stands now; the day's figures come from its sales. */
type Lane = Pick<CheckoutSummary, "checkout_id" | "status" | "cashier" | "shift_started_at" | "queue_length"> & {
  transactions: number;
  lastSaleAt: string;
  /** Who rang up the sales; the current cashier when there is one. */
  rungUpBy: Cashier;
};

const STORE_ID = "store-001";
const BUSINESS_DATE = "2026-10-09";
/** When the store opened, for a lane with no shift start. */
const STORE_OPENED_AT = "2026-10-09T07:00:00Z";

const LINH: Cashier = { staff_id: "EMP-014", name: "Linh Tran" };
const MINH: Cashier = { staff_id: "EMP-022", name: "Minh Pham" };
const BAO: Cashier = { staff_id: "EMP-031", name: "Bao Le" };

const LANES: Lane[] = [
  {
    checkout_id: "CK01",
    status: CHECKOUT_STATUS.Open,
    cashier: LINH,
    shift_started_at: "2026-10-09T07:00:00Z",
    queue_length: 3,
    transactions: 96,
    lastSaleAt: "2026-10-09T11:42:00Z",
    rungUpBy: LINH,
  },
  {
    checkout_id: "CK02",
    status: CHECKOUT_STATUS.Paused,
    cashier: MINH,
    shift_started_at: "2026-10-09T09:00:00Z",
    queue_length: 0,
    transactions: 51,
    lastSaleAt: "2026-10-09T11:15:00Z",
    rungUpBy: MINH,
  },
  {
    checkout_id: "CK03",
    status: CHECKOUT_STATUS.Closed,
    cashier: null,
    shift_started_at: null,
    queue_length: 0,
    transactions: 19,
    lastSaleAt: "2026-10-09T08:58:00Z",
    // Closed now; this cashier worked it this morning.
    rungUpBy: BAO,
  },
];

/** Shelf price of each SKU the demo store stocks (./store.ts). */
export const DEMO_PRICES: Readonly<Record<string, number>> = {
  P001: 3.49,
  P002: 2.99,
  P003: 4.25,
  P004: 1.89,
  P005: 5.49,
  P006: 3.79,
  P007: 2.49,
  P008: 6.99,
  P009: 8.99,
  P010: 4.99,
  P011: 0.79,
  P012: 1.29,
};
const SKUS = Object.keys(DEMO_PRICES);

/** Payment methods weighted the way shoppers pay: mostly card, then mobile, then cash. */
const PAYMENT_MIX = [
  PAYMENT_METHOD.Card,
  PAYMENT_METHOD.Card,
  PAYMENT_METHOD.Card,
  PAYMENT_METHOD.Card,
  PAYMENT_METHOD.Mobile,
  PAYMENT_METHOD.Mobile,
  PAYMENT_METHOD.Cash,
] as const;

/** A stable seed from an id, so a lane gets the same sales on every load. */
function seedOf(id: string): number {
  let hash = 2166136261;
  for (let i = 0; i < id.length; i += 1) hash = Math.imul(hash ^ id.charCodeAt(i), 16777619);
  return hash >>> 0;
}

const cents = (value: number) => Math.round(value * 100) / 100;

/** One basket: a few distinct SKUs, mostly one or two of each, now and then a big shop. */
function basket(random: () => number): CheckoutLine[] {
  const big = random() < 0.12;
  const kinds = big ? 5 + Math.floor(random() * 6) : 1 + Math.floor(random() * 4);
  // Fisher–Yates: a comparator that returns random numbers would sort differently per engine.
  const skus = [...SKUS];
  for (let i = skus.length - 1; i > 0; i -= 1) {
    const j = Math.floor(random() * (i + 1));
    [skus[i], skus[j]] = [skus[j], skus[i]];
  }
  return skus.slice(0, kinds).map((sku) => {
    const quantity = 1 + Math.floor(random() * (big ? 6 : 3));
    const unit_price = DEMO_PRICES[sku];
    return { sku, quantity, unit_price, line_total: cents(quantity * unit_price) };
  });
}

/** Every lane's sales, newest first, made once. */
const SALES = new Map<string, CheckoutTransaction[]>(
  LANES.map((lane) => {
    const random = mulberry32(seedOf(lane.checkout_id));
    const start = Date.parse(lane.shift_started_at ?? STORE_OPENED_AT);
    const end = Date.parse(lane.lastSaleAt);
    const step = (end - start) / lane.transactions;
    const sales = Array.from({ length: lane.transactions }, (_, index): CheckoutTransaction => {
      // Evenly spread with some jitter; the last sale lands exactly on lastSaleAt.
      const at = index === lane.transactions - 1 ? end : start + step * (index + 0.5 + (random() - 0.5) * 0.8);
      const lines = basket(random);
      return {
        transaction_id: `${lane.checkout_id}-${String(index + 1).padStart(4, "0")}`,
        checkout_id: lane.checkout_id,
        store_id: STORE_ID,
        completed_at: new Date(Math.round(at / 1000) * 1000).toISOString(),
        cashier: lane.rungUpBy,
        items: lines.reduce((sum, line) => sum + line.quantity, 0),
        total: cents(lines.reduce((sum, line) => sum + line.line_total, 0)),
        payment_method: pick(random, PAYMENT_MIX),
        lines,
      };
    });
    return [lane.checkout_id, sales.reverse()];
  }),
);

/** A lane's figures, added up from its sales; null for an id with none. A copy per call. */
export function demoCheckout(checkoutId: string): CheckoutSummary | null {
  const lane = LANES.find((item) => item.checkout_id === checkoutId);
  const sales = SALES.get(checkoutId);
  if (!lane || !sales) return null;
  return {
    checkout_id: lane.checkout_id,
    store_id: STORE_ID,
    status: lane.status,
    cashier: lane.cashier ? { ...lane.cashier } : null,
    shift_started_at: lane.shift_started_at,
    business_date: BUSINESS_DATE,
    revenue_today: cents(sales.reduce((sum, sale) => sum + sale.total, 0)),
    transactions_today: sales.length,
    items_scanned_today: sales.reduce((sum, sale) => sum + sale.items, 0),
    queue_length: lane.queue_length,
    last_transaction_at: sales[0]?.completed_at ?? null,
  };
}

/** A lane's sales today, newest first, each with its receipt lines. Empty for an unknown lane. A copy per call. */
export function demoTransactions(checkoutId: string): CheckoutTransaction[] {
  return structuredClone(SALES.get(checkoutId) ?? []);
}
