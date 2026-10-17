import type { CheckoutStatus, PaymentMethod } from "@/enums/checkout.enum";

export type Cashier = {
  staff_id: string;
  name: string;
};

/**
 * One checkout lane today, as the checkout API will serve it.
 * TODO(BE): apps/api serves no checkout data yet; this shape is the FE's proposal
 * for the schema meeting. Money is in the store currency.
 */
export type CheckoutSummary = {
  checkout_id: string;
  store_id: string;
  status: CheckoutStatus;
  /** Who is on the lane now; null while nobody is. */
  cashier: Cashier | null;
  /** ISO timestamp the current cashier's shift started. */
  shift_started_at: string | null;
  /** Store-local date the figures below add up, YYYY-MM-DD. */
  business_date: string;
  revenue_today: number;
  transactions_today: number;
  items_scanned_today: number;
  /** Shoppers waiting in the lane. */
  queue_length: number;
  last_transaction_at: string | null;
};

/**
 * One completed sale at a checkout, as the checkout API will serve it.
 * TODO(BE): the FE's proposal for the schema meeting. Money is in the store currency.
 */
export type CheckoutTransaction = {
  transaction_id: string;
  checkout_id: string;
  store_id: string;
  /** ISO timestamp the payment went through. */
  completed_at: string;
  /** Who rang the sale up; null for a self-service sale. */
  cashier: Cashier | null;
  /** Units sold, the sum of the lines' quantities. */
  items: number;
  /** What the shopper paid, the sum of the lines' totals. */
  total: number;
  payment_method: PaymentMethod;
  /** What was bought, one line per SKU. */
  lines: CheckoutLine[];
};

/** One SKU on a receipt. `sku` is the product's entity id in the twin. */
export type CheckoutLine = {
  sku: string;
  quantity: number;
  unit_price: number;
  /** quantity × unit_price. */
  line_total: number;
};

/** `GET /checkouts/{checkout_id}` response from the API. */
export type CheckoutResponse = {
  summary: CheckoutSummary;
  transactions: CheckoutTransaction[];
};
