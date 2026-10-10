import { motion } from "framer-motion";
import { useMemo } from "react";
import { useTranslation } from "react-i18next";
import type { Promotion } from "@/types/promotion.type";
import { PROMOTION_KIND, PROMOTION_STATUS } from "@/enums/commerce.enum";
import { ENTITY_TYPE } from "@/enums/scene.enum";
import { productRows } from "@/core/twin/productRows";
import { format as f } from "@/core/utils/format";
import { useTwinStore } from "@/state/twin.store";
import { selectedProductId, useUiStore } from "@/state/ui.store";

/** The promotion's discount value, formatted for its kind: "15%", "$1", or "1". */
export function discountOf(promotion: Promotion) {
  return promotion.kind === PROMOTION_KIND.PercentOff
    ? f.percent(promotion.value)
    : promotion.kind === PROMOTION_KIND.AmountOff
      ? f.money(promotion.value)
      : f.count(promotion.value);
}

/** Share of a promotion's run that has passed, 0..1. */
function elapsed(promotion: Promotion, now = Date.now()) {
  const start = Date.parse(promotion.starts_at);
  const end = Date.parse(promotion.ends_at);
  if (!(end > start)) return 0;
  return Math.min(1, Math.max(0, (now - start) / (end - start)));
}

/**
 * The promotion's products as the twin has them now: where they stand and how much is on
 * the shelf. A product selects itself in the 3D view; one the twin lacks says so.
 */
function PromotionProducts({ skus }: { skus: string[] }) {
  const { t } = useTranslation();
  const live = useTwinStore((state) => state.live);
  const select = useUiStore((state) => state.select);
  const selected = useUiStore(selectedProductId);
  const bySku = useMemo(() => new Map(productRows(live?.products ?? []).map((row) => [row.sku, row])), [live]);

  return (
    <ul className="promotion-products" aria-label={t("promotions.products")}>
      {skus.map((sku) => {
        const row = bySku.get(sku);
        return (
          <li key={sku}>
            {row ? (
              <button
                type="button"
                className="promotion-product"
                aria-label={t("promotions.selectProduct", { sku })}
                aria-pressed={selected === sku}
                title={t(`storeStatus.state.${row.state}`)}
                onClick={() => select(sku, ENTITY_TYPE.Product)}
              >
                <span className="store-status-dot" data-state={row.state} />
                <span className="promotion-product-sku">{sku}</span>
                <span className="promotion-product-place">{row.slot_id}</span>
                <span className="promotion-product-stock">
                  {t("promotions.onShelf", { onShelf: row.shelf_quantity, facings: row.facings })}
                </span>
              </button>
            ) : (
              <span className="promotion-product" data-missing>
                <span className="store-status-dot" aria-hidden />
                <span className="promotion-product-sku">{sku}</span>
                <span className="promotion-product-place">{t("promotions.notInStore")}</span>
              </span>
            )}
          </li>
        );
      })}
    </ul>
  );
}

/** The element id of a promotion's card, so the lens can scroll to it. */
export const promotionCardId = (promotionId: string) => `promotion-${promotionId}`;

/** One promotion: status, discount, dates, its products in the store, and what it earned. `focused` flashes it. */
export function PromotionCard({ promotion, focused = false }: { promotion: Promotion; focused?: boolean }) {
  const { t } = useTranslation();
  const discount = discountOf(promotion);
  const progress = elapsed(promotion);

  return (
    <article
      id={promotionCardId(promotion.id)}
      className="promotion-card"
      data-status={promotion.status}
      data-focused={focused || undefined}
    >
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
      <PromotionProducts skus={promotion.skus} />
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
