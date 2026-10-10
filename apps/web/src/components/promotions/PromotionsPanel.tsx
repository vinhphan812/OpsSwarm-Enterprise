import { AnimatePresence, motion } from "framer-motion";
import { useEffect, useState } from "react";
import { useTranslation } from "react-i18next";
import { MetricTile } from "@/components/commerce/MetricTile";
import { Segmented } from "@/components/commerce/Segmented";
import { PromotionIcon } from "@/components/icons";
import { PROMOTION_FLASH_MS } from "@/constants/app.constant";
import { PROMOTION_STATUS, PROMOTION_STATUSES, type PromotionStatus } from "@/enums/commerce.enum";
import { usePromotions } from "@/hooks/commerce.hook";
import { format as f } from "@/core/utils/format";
import { useUiStore } from "@/state/ui.store";
import { PromotionCard, promotionCardId } from "./PromotionCard";

const ALL = "all";
type StatusFilter = PromotionStatus | typeof ALL;

/**
 * Promotions tab of the side panel, read-only: what runs, what earned, and every program by
 * status. A promotion opened from a product's details (`focusPromotion`) is scrolled to and
 * flashes for a moment; a status filter that hides it goes back to all.
 */
export function PromotionsPanel() {
  const { t } = useTranslation();
  const summary = usePromotions();
  const [filter, setFilter] = useState<StatusFilter>(ALL);
  const { promotions } = summary;
  const focusedId = useUiStore((state) => state.focusedPromotionId);
  const focusPromotion = useUiStore((state) => state.focusPromotion);
  const [flashId, setFlashId] = useState<string | null>(null);

  useEffect(() => {
    const focused = promotions.find((promotion) => promotion.id === focusedId);
    // Waits for the promotions to load; the request stays until the card is there.
    if (!focused) return;
    if (filter !== ALL && focused.status !== filter) setFilter(ALL);
    setFlashId(focused.id);
    focusPromotion(null);
  }, [focusedId, promotions, filter, focusPromotion]);

  useEffect(() => {
    if (!flashId) return;
    // After the lens and the list have animated in.
    const scroll = window.setTimeout(() => {
      document.getElementById(promotionCardId(flashId))?.scrollIntoView?.({ behavior: "smooth", block: "center" });
    }, 250);
    const clear = window.setTimeout(() => setFlashId(null), PROMOTION_FLASH_MS);
    return () => {
      window.clearTimeout(scroll);
      window.clearTimeout(clear);
    };
  }, [flashId]);
  const countOf = (status: PromotionStatus) => promotions.filter((promotion) => promotion.status === status).length;
  const shown = filter === ALL ? promotions : promotions.filter((promotion) => promotion.status === filter);

  return (
    <div className="commerce">
      <div className="metric-grid">
        <MetricTile label={t("promotions.activeCount")} value={countOf(PROMOTION_STATUS.Active)} format={f.count} />
        <MetricTile label={t("promotions.revenue")} value={summary.revenue} format={f.money} />
        <MetricTile label={t("promotions.incremental")} value={summary.incremental_revenue} format={f.money} />
        <MetricTile label={t("promotions.discountCost")} value={summary.discount_cost} format={f.money} />
      </div>

      <section>
        <h2 className="activity-section-title">
          {t("promotions.list")}
          <span className="activity-count">{shown.length}</span>
        </h2>
        <Segmented
          variant="chips"
          label={t("promotions.filter")}
          layoutId="promotion-filter"
          value={filter}
          onChange={setFilter}
          options={[
            { value: ALL, label: t("promotions.all"), badge: promotions.length },
            ...PROMOTION_STATUSES.map((status) => ({
              value: status,
              label: t(`promotions.status.${status}`),
              badge: countOf(status),
            })),
          ]}
        />
        <AnimatePresence initial={false} mode="popLayout">
          {shown.length ? (
            <motion.div key="list" className="promotion-list" initial={{ opacity: 0 }} animate={{ opacity: 1 }} exit={{ opacity: 0 }}>
              <AnimatePresence initial={false}>
                {shown.map((promotion) => (
                  <motion.div
                    key={promotion.id}
                    layout
                    initial={{ opacity: 0, y: 8 }}
                    animate={{ opacity: 1, y: 0 }}
                    exit={{ opacity: 0, scale: 0.98 }}
                    transition={{ duration: 0.22, ease: "easeOut" }}
                  >
                    <PromotionCard promotion={promotion} focused={promotion.id === flashId} />
                  </motion.div>
                ))}
              </AnimatePresence>
            </motion.div>
          ) : (
            <motion.div
              key={`empty-${filter}`}
              className="empty"
              initial={{ opacity: 0, y: 4 }}
              animate={{ opacity: 1, y: 0 }}
              exit={{ opacity: 0 }}
            >
              <PromotionIcon className="empty-icon" />
              <p>{t(filter === ALL ? "promotions.empty" : "promotions.emptyFiltered")}</p>
            </motion.div>
          )}
        </AnimatePresence>
      </section>
    </div>
  );
}
