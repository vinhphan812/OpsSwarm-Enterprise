import { Button, Chip } from "@heroui/react";
import { useState } from "react";
import { useTranslation } from "react-i18next";
import { format } from "@/core/utils/format";
import { CHECKOUT_STATUS, type CheckoutStatus } from "@/enums/checkout.enum";
import { useCheckoutSummary } from "@/hooks/checkout.hook";
import { DemoBadge } from "./DemoBadge";
import { Figures, InspectorCard } from "./InspectorCard";
import { PaymentsDialog } from "./PaymentsDialog";

const STATUS_COLOR: Record<CheckoutStatus, "success" | "warning" | "default"> = {
  [CHECKOUT_STATUS.Open]: "success",
  [CHECKOUT_STATUS.Paused]: "warning",
  [CHECKOUT_STATUS.Closed]: "default",
};

/** Today's figures of the selected checkout: status, cashier, sales, and a way into its payments. TODO(BE): none served yet. */
export function CheckoutInspector({ checkoutId, title }: { checkoutId: string; title: string }) {
  const { t } = useTranslation();
  const summary = useCheckoutSummary(checkoutId);
  const none = t("checkout.none");
  const [paymentsOpen, setPaymentsOpen] = useState(false);

  const badges = summary ? (
    <>
      <Chip size="sm" variant="flat" color={STATUS_COLOR[summary.status]}>
        {t(`checkout.status.${summary.status}`)}
      </Chip>
      <DemoBadge />
    </>
  ) : null;

  return (
    <InspectorCard
      title={checkoutId}
      subtitle={title}
      label={t("inspector.fixtureLabel", { title, id: checkoutId })}
      badges={badges}
    >
      {summary ? (
        <Figures
          rows={[
            [t("checkout.cashier"), summary.cashier ? `${summary.cashier.name} (${summary.cashier.staff_id})` : t("checkout.noCashier")],
            [t("checkout.shiftSince"), summary.shift_started_at ? format.hour(summary.shift_started_at) : none],
            [t("checkout.revenueToday"), format.moneyExact(summary.revenue_today)],
            [t("checkout.transactions"), format.count(summary.transactions_today)],
            [
              t("checkout.averageBasket"),
              summary.transactions_today ? format.moneyExact(summary.revenue_today / summary.transactions_today) : none,
            ],
            [t("checkout.itemsScanned"), format.count(summary.items_scanned_today)],
            [t("checkout.queue"), format.count(summary.queue_length)],
            [t("checkout.lastSale"), summary.last_transaction_at ? format.hour(summary.last_transaction_at) : none],
          ]}
        />
      ) : null}
      {summary ? (
        <>
          <Button
            size="sm"
            radius="sm"
            variant="flat"
            className="mt-3 w-full cursor-pointer font-semibold"
            onPress={() => setPaymentsOpen(true)}
          >
            {t("checkout.viewPayments")}
          </Button>
          <PaymentsDialog
            isOpen={paymentsOpen}
            onClose={() => setPaymentsOpen(false)}
            checkoutId={checkoutId}
            businessDate={summary.business_date}
          />
        </>
      ) : (
        <p className="text-default-500">{t("checkout.noData")}</p>
      )}
    </InspectorCard>
  );
}
