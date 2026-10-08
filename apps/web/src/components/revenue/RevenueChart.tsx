import { AnimatePresence, motion } from "framer-motion";
import { useState } from "react";
import { useTranslation } from "react-i18next";
import type { RevenueSummary } from "@/types/revenue.type";
import { BUCKET_SIZE } from "@/enums/commerce.enum";
import { useFormat } from "@/hooks/format.hook";

/** Revenue per hour (today) or per day (longer windows), as one series of bars with a hover tooltip. */
export function RevenueChart({ summary }: { summary: RevenueSummary }) {
  const { t } = useTranslation();
  const f = useFormat();
  const [hovered, setHovered] = useState<number | null>(null);
  const { buckets } = summary;
  const byHour = summary.bucket_size === BUCKET_SIZE.Hour;
  const time = (iso: string) => (byHour ? f.hour(iso) : f.day(iso));
  const max = Math.max(0, ...buckets.map((bucket) => bucket.revenue));
  const ticks = [0, Math.round((buckets.length - 1) / 2), buckets.length - 1];
  const title = t(byHour ? "revenue.byHour" : "revenue.byDay");

  return (
    <figure className="revenue-chart" aria-label={title}>
      <div className="revenue-chart-plot" onMouseLeave={() => setHovered(null)}>
        <div className="revenue-chart-grid" aria-hidden>
          <span />
          <span />
          <span />
        </div>
        <div className="revenue-chart-bars" style={{ gridTemplateColumns: `repeat(${buckets.length}, minmax(0, 1fr))` }} aria-hidden>
          {buckets.map((bucket, i) => (
            <div
              key={bucket.start}
              className="revenue-chart-slot"
              data-hovered={hovered === i || undefined}
              onMouseEnter={() => setHovered(i)}
            >
              <motion.div
                className="revenue-chart-bar"
                data-zero={bucket.revenue === 0 || undefined}
                initial={{ height: 0 }}
                animate={{ height: `${max ? (bucket.revenue / max) * 100 : 0}%` }}
                transition={{ duration: 0.55, delay: i * 0.012, ease: [0.16, 1, 0.3, 1] }}
              />
            </div>
          ))}
        </div>
        <AnimatePresence>
          {max === 0 ? (
            <motion.p
              key="empty"
              className="revenue-chart-empty"
              initial={{ opacity: 0 }}
              animate={{ opacity: 1 }}
              exit={{ opacity: 0 }}
            >
              {t("revenue.chartEmpty")}
            </motion.p>
          ) : null}
        </AnimatePresence>
        <AnimatePresence>
          {hovered === null ? null : (
            <motion.div
              key="tip"
              className="revenue-chart-tip"
              style={{ left: `${((hovered + 0.5) / buckets.length) * 100}%` }}
              initial={{ opacity: 0, y: 4 }}
              animate={{ opacity: 1, y: 0 }}
              exit={{ opacity: 0 }}
              transition={{ duration: 0.12 }}
            >
              <span className="revenue-chart-tip-time">{time(buckets[hovered].start)}</span>
              <strong>{f.moneyExact(buckets[hovered].revenue)}</strong>
            </motion.div>
          )}
        </AnimatePresence>
      </div>
      <div className="revenue-chart-axis" aria-hidden>
        {ticks.map((i) => (
          <span key={i}>{time(buckets[i].start)}</span>
        ))}
      </div>
      {/* The same figures as a table, for screen readers. */}
      <table className="sr-only">
        <caption>{title}</caption>
        <tbody>
          {buckets.map((bucket) => (
            <tr key={bucket.start}>
              <th scope="row">{time(bucket.start)}</th>
              <td>{f.moneyExact(bucket.revenue)}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </figure>
  );
}
