import { isDemoMode } from "@/core/twin/demoMode";
import { demoCheckout, demoTransactions } from "@/fixtures/demo/checkouts";
import type { CheckoutSummary, CheckoutTransaction } from "@/types/checkout.type";

/**
 * Today's figures of one checkout, or null while there are none.
 * TODO(BE): apps/api serves no checkouts yet; read them here once the schema
 * (`CheckoutSummary`) is agreed. Until then the checkout card says so, except under
 * `?twin=demo`, which shows demo figures.
 */
export function useCheckoutSummary(checkoutId: string): CheckoutSummary | null {
  return isDemoMode() ? demoCheckout(checkoutId) : null;
}

/**
 * Today's sales at one checkout, newest first, read only while `enabled` (the dialog is
 * open). TODO(BE): apps/api serves no checkout transactions yet (`CheckoutTransaction`);
 * `?twin=demo` shows demo sales.
 */
export function useCheckoutTransactions(checkoutId: string, enabled: boolean): CheckoutTransaction[] {
  return enabled && isDemoMode() ? demoTransactions(checkoutId) : [];
}
