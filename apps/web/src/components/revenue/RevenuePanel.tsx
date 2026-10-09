import { useState } from "react";
import { useTranslation } from "react-i18next";
import { MetricTile } from "@/components/commerce/MetricTile";
import { Segmented } from "@/components/commerce/Segmented";
import { relativeChange } from "@/core/utils/format";
import { BUCKET_SIZE, REVENUE_PERIOD, REVENUE_PERIODS, type RevenuePeriod } from "@/enums/commerce.enum";
import { useRevenue } from "@/hooks/commerce.hook";
import { format as f } from "@/core/utils/format";
import { CategoryShare } from "./CategoryShare";
import { RevenueChart } from "./RevenueChart";
import { SkuList } from "./SkuList";

/** Revenue tab of the side panel: headline figures, the sales curve, categories, and best and worst sellers. */
export function RevenuePanel() {
  const { t } = useTranslation();
  const [period, setPeriod] = useState<RevenuePeriod>(REVENUE_PERIOD.Today);
  const summary = useRevenue(period);
  const { previous } = summary;

  return (
    <div className="commerce">
      <Segmented
        label={t("revenue.period.label")}
        layoutId="revenue-period"
        value={period}
        onChange={setPeriod}
        options={REVENUE_PERIODS.map((value) => ({ value, label: t(`revenue.period.${value}`) }))}
      />

      <div className="metric-grid">
        <MetricTile
          wide
          label={t("revenue.revenue")}
          value={summary.revenue}
          format={f.money}
          change={relativeChange(summary.revenue, previous.revenue)}
        />
        <MetricTile
          label={t("revenue.transactions")}
          value={summary.transactions}
          format={f.count}
          change={relativeChange(summary.transactions, previous.transactions)}
        />
        <MetricTile
          label={t("revenue.averageBasket")}
          value={summary.average_basket}
          format={f.money}
          change={relativeChange(summary.average_basket, previous.average_basket)}
        />
        <MetricTile label={t("revenue.marginRate")} value={summary.margin_rate} format={f.percent} />
        <MetricTile
          tone="alert"
          label={t("revenue.lostToStockout")}
          hint={t("revenue.lostHint")}
          value={summary.lost_to_stockout}
          format={f.money}
        />
      </div>

      <section>
        <h2 className="activity-section-title">
          {t(summary.bucket_size === BUCKET_SIZE.Hour ? "revenue.byHour" : "revenue.byDay")}
        </h2>
        <RevenueChart key={period} summary={summary} />
      </section>

      <section>
        <h2 className="activity-section-title">{t("revenue.byCategory")}</h2>
        <CategoryShare categories={summary.categories} />
      </section>

      <section>
        <h2 className="activity-section-title">
          {t("revenue.topSkus")}
          <span className="activity-count">{summary.top_skus.length}</span>
        </h2>
        <SkuList skus={summary.top_skus} label={t("revenue.topSkus")} />
      </section>

      <section>
        <h2 className="activity-section-title">
          {t("revenue.slowSkus")}
          <span className="activity-count">{summary.slow_skus.length}</span>
        </h2>
        <SkuList skus={summary.slow_skus} label={t("revenue.slowSkus")} />
      </section>
    </div>
  );
}
