import { motion } from "framer-motion";
import { useTranslation } from "react-i18next";
import type { Promotion } from "@/types/promotion.type";
import { PROMOTION_KIND, PROMOTION_STATUS } from "@/enums/commerce.enum";
import { useFormat } from "@/hooks/format.hook";

/** Share of a promotion's run that has passed, 0..1. */
function elapsed(promotion: Promotion, now = Date.now()) {
  const start = Date.parse(promotion.starts_at);
  const end = Date.parse(promotion.ends_at);
  if (!(end > start)) return 0;
  return Math.min(1, Math.max(0, (now - start) / (end - start)));
}

/** One promotion: status, discount, dates, scope, and what it earned. */
export function PromotionCard({ promotion }: { promotion: Promotion }) {
  const { t } = useTranslation();
  const f = useFormat();
  const discount =
    promotion.kind === PROMOTION_KIND.PercentOff
      ? f.percent(promotion.value)
      : promotion.kind === PROMOTION_KIND.AmountOff
        ? f.money(promotion.value)
        : f.count(promotion.value);
  const progress = elapsed(promotion);

  return (
    <article className="promotion-card" data-status={promotion.status}>
      <header className="promotion-card-head">
        <span className="promotion-status">
          <span className="promotion-status-dot" aria-hidden />
          {t(`promotions.status.${promotion.status}`)}
        </span>
        <span className="promotion-kind">{t(`promotions.kind.${promotion.kind}`, { value: discount })}</span>
      </header>
      <h3 className="promotion-name">{promotion.name}</h3>
      <p className="promotion-meta">
        {t("promotions.dates", { start: f.day(promotion.starts_at), end: f.day(promotion.ends_at) })} ·{" "}
        {t("promotions.skus", { count: promotion.skus.length })}
      </p>
      {promotion.status === PROMOTION_STATUS.Active ? (
        <div className="promotion-progress" aria-hidden>
          <motion.span initial={{ width: 0 }} animate={{ width: `${progress * 100}%` }} transition={{ duration: 0.6 }} />
        </div>
      ) : null}
      <dl className="promotion-figures">
        <div>
          <dt>{t("promotions.revenue")}</dt>
          <dd>{f.money(promotion.revenue)}</dd>
        </div>
        <div>
          <dt>{t("promotions.incremental")}</dt>
          <dd>{f.money(promotion.incremental_revenue)}</dd>
        </div>
        <div>
          <dt>{t("promotions.discountCost")}</dt>
          <dd>{f.money(promotion.discount_cost)}</dd>
        </div>
      </dl>
    </article>
  );
}
