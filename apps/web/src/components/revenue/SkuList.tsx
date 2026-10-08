import { AnimatePresence, motion } from "framer-motion";
import { useTranslation } from "react-i18next";
import { SKU_LIST_SIZE } from "@/constants/commerce.constant";
import type { SkuRevenue } from "@/core/api/types";
import { useFormat } from "@/hooks/format.hook";

/** Ranked SKUs with their revenue, each with a thin bar relative to the first row. */
export function SkuList({ skus, label }: { skus: SkuRevenue[]; label: string }) {
  const { t } = useTranslation();
  const f = useFormat();
  const rows = skus.slice(0, SKU_LIST_SIZE);
  const max = Math.max(0, ...rows.map((sku) => sku.revenue));

  return (
    <AnimatePresence initial={false} mode="popLayout">
      {rows.length ? (
        <motion.ol key="list" className="sku-list" aria-label={label} initial={{ opacity: 0 }} animate={{ opacity: 1 }} exit={{ opacity: 0 }}>
          {rows.map((sku, i) => (
            <motion.li
              key={sku.sku}
              layout
              className="sku-row"
              initial={{ opacity: 0, y: 6 }}
              animate={{ opacity: 1, y: 0 }}
              transition={{ duration: 0.22, delay: i * 0.04 }}
            >
              <span className="sku-rank">{i + 1}</span>
              <span className="sku-name">
                <strong>{sku.sku}</strong> {sku.name}
                <small>{t("revenue.skuLine", { units: f.count(sku.units), facings: sku.facings })}</small>
              </span>
              <span className="sku-revenue">{f.money(sku.revenue)}</span>
              <span className="sku-bar" style={{ width: `${max ? (sku.revenue / max) * 100 : 0}%` }} aria-hidden />
            </motion.li>
          ))}
        </motion.ol>
      ) : (
        <motion.p key="empty" className="empty empty-compact" initial={{ opacity: 0 }} animate={{ opacity: 1 }} exit={{ opacity: 0 }}>
          {t("revenue.skusEmpty")}
        </motion.p>
      )}
    </AnimatePresence>
  );
}
