import { AnimatePresence, motion } from "framer-motion";
import { useTranslation } from "react-i18next";
import { SKU_LIST_SIZE } from "@/constants/commerce.constant";
import type { SkuRevenue } from "@/types/revenue.type";
import { format as f } from "@/core/utils/format";
import { ENTITY_TYPE } from "@/enums/scene.enum";
import { selectedProductId, useUiStore } from "@/state/ui.store";

/** Ranked SKUs with their revenue, each with a thin bar relative to the first row. A row selects its product. */
export function SkuList({ skus, label }: { skus: SkuRevenue[]; label: string }) {
  const { t } = useTranslation();
  const select = useUiStore((state) => state.select);
  const selected = useUiStore(selectedProductId);
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
              initial={{ opacity: 0, y: 6 }}
              animate={{ opacity: 1, y: 0 }}
              transition={{ duration: 0.22, delay: i * 0.04 }}
            >
              <button
                type="button"
                className="sku-row"
                aria-label={t("revenue.selectProduct", { sku: sku.sku, name: sku.name })}
                aria-pressed={selected === sku.sku}
                onClick={() => select(sku.sku, ENTITY_TYPE.Product)}
              >
                <span className="sku-rank">{i + 1}</span>
                <span className="sku-name">
                  <strong>{sku.sku}</strong> {sku.name}
                  <small>{t("revenue.skuLine", { units: f.count(sku.units), facings: sku.facings })}</small>
                </span>
                <span className="sku-revenue">{f.money(sku.revenue)}</span>
                <span className="sku-bar" style={{ width: `${max ? (sku.revenue / max) * 100 : 0}%` }} aria-hidden />
              </button>
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
