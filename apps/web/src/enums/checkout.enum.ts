/** Whether a checkout lane is taking shoppers. TODO(BE): agree the values with the checkout API. */
export const CHECKOUT_STATUS = {
  Open: "open",
  /** Staffed, but not taking new shoppers (break, till count). */
  Paused: "paused",
  Closed: "closed",
} as const;
export type CheckoutStatus = (typeof CHECKOUT_STATUS)[keyof typeof CHECKOUT_STATUS];

/** How a shopper paid. TODO(BE): agree the values with the checkout API. */
export const PAYMENT_METHOD = {
  Card: "card",
  Cash: "cash",
  Mobile: "mobile",
} as const;
export type PaymentMethod = (typeof PAYMENT_METHOD)[keyof typeof PAYMENT_METHOD];
export const PAYMENT_METHODS: readonly PaymentMethod[] = Object.values(PAYMENT_METHOD);
