import { Fragment, useMemo, useState } from "react";
import { useTranslation } from "react-i18next";
import { ListDialog } from "@/components/common/ListDialog";
import { Segmented } from "@/components/commerce/Segmented";
import { format } from "@/core/utils/format";
import { PAYMENT_METHODS, type PaymentMethod } from "@/enums/checkout.enum";
import { ENTITY_TYPE } from "@/enums/scene.enum";
import { useCheckoutTransactions } from "@/hooks/checkout.hook";
import { useUiStore } from "@/state/ui.store";
import { DemoBadge } from "./DemoBadge";
import type { CheckoutTransaction } from "@/types/checkout.type";

const ALL = "all";
type MethodFilter = PaymentMethod | typeof ALL;
const FILTERS: readonly MethodFilter[] = [ALL, ...PAYMENT_METHODS];

/** Sales whose id or cashier contains `query`, ignoring case. */
function matchSales(sales: CheckoutTransaction[], query: string) {
  const needle = query.trim().toLowerCase();
  if (!needle) return sales;
  return sales.filter((sale) =>
    [sale.transaction_id, sale.cashier?.name ?? "", sale.cashier?.staff_id ?? ""].some((field) =>
      field.toLowerCase().includes(needle),
    ),
  );
}

type PaymentsDialogProps = {
  isOpen: boolean;
  onClose: () => void;
  checkoutId: string;
  /** Store-local date the sales are from, YYYY-MM-DD. */
  businessDate: string;
};

/**
 * Today's payments at one checkout, newest first: totals for what is shown, then each
 * sale with its time, cashier, items, method, and total. Clicking a sale opens its
 * receipt under it; a SKU on the receipt selects that product in the 3D view and closes
 * the dialog. TODO(BE): no transactions are served yet (`useCheckoutTransactions`).
 */
export function PaymentsDialog({ isOpen, onClose, checkoutId, businessDate }: PaymentsDialogProps) {
  const { t } = useTranslation();
  const sales = useCheckoutTransactions(checkoutId, isOpen);
  const [filter, setFilter] = useState<MethodFilter>(ALL);
  const [query, setQuery] = useState("");
  const [openId, setOpenId] = useState<string | null>(null);
  const select = useUiStore((state) => state.select);
  const toggle = (id: string) => setOpenId((current) => (current === id ? null : id));
  const showProduct = (sku: string) => {
    select(sku, ENTITY_TYPE.Product);
    onClose();
  };

  const shown = useMemo(
    () => matchSales(filter === ALL ? sales : sales.filter((sale) => sale.payment_method === filter), query),
    [sales, filter, query],
  );
  const revenue = shown.reduce((sum, sale) => sum + sale.total, 0);
  const countOf = (value: MethodFilter) =>
    value === ALL ? sales.length : sales.filter((sale) => sale.payment_method === value).length;

  return (
    <ListDialog
      isOpen={isOpen}
      onClose={onClose}
      title={t("checkout.payments.title", { id: checkoutId })}
      subtitle={t("checkout.payments.subtitle", { date: format.day(`${businessDate}T12:00:00Z`) })}
      badges={<DemoBadge />}
      summary={
        <dl className="dialog-summary">
          <div>
            <dt>{t("checkout.payments.transactions")}</dt>
            <dd>{format.count(shown.length)}</dd>
          </div>
          <div>
            <dt>{t("checkout.payments.revenue")}</dt>
            <dd>{format.moneyExact(revenue)}</dd>
          </div>
          <div>
            <dt>{t("checkout.payments.averageBasket")}</dt>
            <dd>{shown.length ? format.moneyExact(revenue / shown.length) : t("checkout.none")}</dd>
          </div>
        </dl>
      }
      toolbar={
        <>
          <Segmented
            variant="chips"
            label={t("checkout.payments.filter")}
            layoutId="payment-method-filter"
            value={filter}
            onChange={setFilter}
            options={FILTERS.map((value) => ({
              value,
              label: value === ALL ? t("checkout.payments.all") : t(`checkout.payments.method.${value}`),
              badge: countOf(value),
            }))}
          />
          <input
            type="search"
            className="text-field dialog-search"
            aria-label={t("checkout.payments.search")}
            placeholder={t("checkout.payments.search")}
            value={query}
            onChange={(event) => setQuery(event.target.value)}
            autoComplete="off"
          />
        </>
      }
      empty={sales.length === 0 ? t("checkout.payments.none") : t("checkout.payments.empty")}
      isEmpty={shown.length === 0}
    >
      <table className="data-table" aria-label={t("checkout.payments.title", { id: checkoutId })}>
        <thead>
          <tr>
            <th scope="col">{t("checkout.payments.time")}</th>
            <th scope="col">{t("checkout.payments.transaction")}</th>
            <th scope="col">{t("checkout.payments.cashier")}</th>
            <th scope="col" className="num">{t("checkout.payments.items")}</th>
            <th scope="col">{t("checkout.payments.paidBy")}</th>
            <th scope="col" className="num">{t("checkout.payments.total")}</th>
          </tr>
        </thead>
        <tbody>
          {shown.map((sale) => {
            const open = openId === sale.transaction_id;
            return (
              <Fragment key={sale.transaction_id}>
                <tr
                  tabIndex={0}
                  aria-expanded={open}
                  aria-label={t("checkout.payments.showReceipt", { id: sale.transaction_id })}
                  data-open={open}
                  onClick={() => toggle(sale.transaction_id)}
                  onKeyDown={(event) => {
                    if (event.key === "Enter" || event.key === " ") {
                      event.preventDefault();
                      toggle(sale.transaction_id);
                    }
                  }}
                >
                  <td>
                    <span className="receipt-caret" aria-hidden="true" />
                    <time dateTime={sale.completed_at}>{format.hour(sale.completed_at)}</time>
                  </td>
                  <td className="font-semibold">{sale.transaction_id}</td>
                  <td className="text-ink-muted">{sale.cashier?.name ?? t("checkout.payments.selfService")}</td>
                  <td className="num">{sale.items}</td>
                  <td>{t(`checkout.payments.method.${sale.payment_method}`)}</td>
                  <td className="num font-semibold">{format.moneyExact(sale.total)}</td>
                </tr>
                {open ? (
                  <tr className="receipt-row">
                    <td colSpan={6}>
                      <table className="receipt" aria-label={t("checkout.payments.receipt", { id: sale.transaction_id })}>
                        <thead>
                          <tr>
                            <th scope="col">{t("checkout.payments.sku")}</th>
                            <th scope="col" className="num">{t("checkout.payments.quantity")}</th>
                            <th scope="col" className="num">{t("checkout.payments.unitPrice")}</th>
                            <th scope="col" className="num">{t("checkout.payments.lineTotal")}</th>
                          </tr>
                        </thead>
                        <tbody>
                          {sale.lines.map((line) => (
                            <tr key={line.sku}>
                              <td>
                                <button
                                  type="button"
                                  className="receipt-sku"
                                  aria-label={t("checkout.payments.showProduct", { sku: line.sku })}
                                  onClick={() => showProduct(line.sku)}
                                >
                                  {line.sku}
                                </button>
                              </td>
                              <td className="num">{line.quantity}</td>
                              <td className="num text-ink-muted">{format.moneyExact(line.unit_price)}</td>
                              <td className="num">{format.moneyExact(line.line_total)}</td>
                            </tr>
                          ))}
                        </tbody>
                        <tfoot>
                          <tr>
                            <td>{t(`checkout.payments.method.${sale.payment_method}`)}</td>
                            <td className="num">{sale.items}</td>
                            <td />
                            <td className="num font-semibold">{format.moneyExact(sale.total)}</td>
                          </tr>
                        </tfoot>
                      </table>
                    </td>
                  </tr>
                ) : null}
              </Fragment>
            );
          })}
        </tbody>
      </table>
    </ListDialog>
  );
}
