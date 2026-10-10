import { CHECKOUT_STATUS, PAYMENT_METHOD, type CheckoutStatus } from "@/enums/checkout.enum";
import type { CheckoutSummary, CheckoutTransaction } from "@/types/checkout.type";

/**
 * Checkout data in the shape the checkout API is expected to serve (`CheckoutSummary`,
 * `CheckoutTransaction`). Test data only: the app shows no checkout figures until
 * apps/api serves them.
 */

const LINH = { staff_id: "EMP-014", name: "Linh Tran" };

export const SAMPLE_SALES: CheckoutTransaction[] = [
  {
    transaction_id: "CK01-0003",
    checkout_id: "CK01",
    store_id: "store-001",
    completed_at: "2026-10-09T11:42:00Z",
    cashier: LINH,
    items: 3,
    total: 9.97,
    payment_method: PAYMENT_METHOD.Cash,
    lines: [
      { sku: "P001", quantity: 2, unit_price: 3.49, line_total: 6.98 },
      { sku: "P002", quantity: 1, unit_price: 2.99, line_total: 2.99 },
    ],
  },
  {
    transaction_id: "CK01-0002",
    checkout_id: "CK01",
    store_id: "store-001",
    completed_at: "2026-10-09T10:15:00Z",
    cashier: LINH,
    items: 1,
    total: 8.99,
    payment_method: PAYMENT_METHOD.Card,
    lines: [{ sku: "P009", quantity: 1, unit_price: 8.99, line_total: 8.99 }],
  },
  {
    transaction_id: "CK01-0001",
    checkout_id: "CK01",
    store_id: "store-001",
    completed_at: "2026-10-09T07:20:00Z",
    cashier: LINH,
    items: 4,
    total: 7.56,
    payment_method: PAYMENT_METHOD.Mobile,
    lines: [{ sku: "P004", quantity: 4, unit_price: 1.89, line_total: 7.56 }],
  },
];

function summary(checkoutId: string, status: CheckoutStatus): CheckoutSummary {
  const open = status !== CHECKOUT_STATUS.Closed;
  return {
    checkout_id: checkoutId,
    store_id: "store-001",
    status,
    cashier: open ? LINH : null,
    shift_started_at: open ? "2026-10-09T07:00:00Z" : null,
    business_date: "2026-10-09",
    revenue_today: 26.52,
    transactions_today: 3,
    items_scanned_today: 8,
    queue_length: open ? 2 : 0,
    last_transaction_at: "2026-10-09T11:42:00Z",
  };
}

/** CK01 open, CK02 paused, CK03 closed. */
export const SAMPLE_CHECKOUTS: Record<string, CheckoutSummary> = {
  CK01: summary("CK01", CHECKOUT_STATUS.Open),
  CK02: summary("CK02", CHECKOUT_STATUS.Paused),
  CK03: summary("CK03", CHECKOUT_STATUS.Closed),
};
