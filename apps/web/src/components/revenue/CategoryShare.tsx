import { motion } from "framer-motion";
import { useTranslation } from "react-i18next";
import { CATEGORY_COLOR, OTHER_CATEGORY_COLOR } from "@/constants/commerce.constant";
import type { CategoryRevenue } from "@/types/revenue.type";
import type { StockKind } from "@/enums/scene.enum";
import { useFormat } from "@/hooks/format.hook";

const colorOf = (category: string) => CATEGORY_COLOR[category as StockKind] ?? OTHER_CATEGORY_COLOR;

/** Share of revenue per category: one stacked bar, and a legend that names every segment. */
export function CategoryShare({ categories }: { categories: CategoryRevenue[] }) {
  const { t } = useTranslation();
  const f = useFormat();
  const total = categories.reduce((sum, category) => sum + category.revenue, 0);
  const name = (category: string) => t(`scene.stock.${category as StockKind}`, { defaultValue: category });

  return (
    <div className="category-share">
      <div className="category-share-bar" role="img" aria-label={t("revenue.byCategory")}>
        {categories.map((category, i) => (
          <motion.span
            key={category.category}
            className="category-share-segment"
            style={{ background: colorOf(category.category) }}
            initial={{ flexGrow: 0 }}
            animate={{ flexGrow: total ? category.revenue / total : 0 }}
            transition={{ duration: 0.6, delay: i * 0.05, ease: [0.16, 1, 0.3, 1] }}
            title={`${name(category.category)}: ${f.moneyExact(category.revenue)}`}
          />
        ))}
      </div>
      <ul className="category-share-legend">
        {categories.map((category) => (
          <li key={category.category}>
            <span className="category-share-swatch" style={{ background: colorOf(category.category) }} aria-hidden />
            <span className="category-share-name">{name(category.category)}</span>
            <span className="category-share-value">{f.money(category.revenue)}</span>
            <span className="category-share-pct">{f.percent(total ? category.revenue / total : 0)}</span>
          </li>
        ))}
      </ul>
    </div>
  );
}
