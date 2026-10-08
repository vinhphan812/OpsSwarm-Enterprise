import { useTranslation } from "react-i18next";
import { AlertIcon, TrendIcon } from "@/components/icons";
import { format as f } from "@/core/utils/format";
import { AnimatedNumber } from "./AnimatedNumber";

type MetricTileProps = {
  label: string;
  value: number;
  format: (value: number) => string;
  /** Relative change from the previous window; null when there is none to compare with. */
  change?: number | null;
  /** `alert` marks a figure that is bad news by nature, such as sales lost to stockouts. */
  tone?: "default" | "alert";
  hint?: string;
  wide?: boolean;
};

/** One headline figure: label, counting value, and how it moved. */
export function MetricTile({ label, value, format, change, tone = "default", hint, wide }: MetricTileProps) {
  return (
    <div className="metric" data-tone={tone} data-wide={wide || undefined} title={hint}>
      <span className="metric-label">
        {tone === "alert" ? <AlertIcon className="metric-alert-icon" /> : null}
        {label}
      </span>
      <strong className="metric-value">
        <AnimatedNumber value={value} format={format} />
      </strong>
      {change === undefined ? null : <ChangeBadge change={change} />}
    </div>
  );
}

/** "▲ +8% vs previous": the arrow carries the direction in color, the text stays in ink. */
function ChangeBadge({ change }: { change: number | null }) {
  const { t } = useTranslation();
  if (change === null || change === 0) {
    return (
      <span className="metric-change" data-trend="flat" title={change === null ? t("revenue.noBaseline") : undefined}>
        {change === null ? "—" : f.change(0)} <span className="metric-change-note">{t("revenue.vsPrevious")}</span>
      </span>
    );
  }
  const up = change > 0;
  return (
    <span className="metric-change" data-trend={up ? "up" : "down"}>
      <TrendIcon up={up} className="metric-trend-icon" />
      {f.change(change)} <span className="metric-change-note">{t("revenue.vsPrevious")}</span>
    </span>
  );
}
