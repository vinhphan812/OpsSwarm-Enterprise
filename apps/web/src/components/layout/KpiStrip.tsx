import { useState } from "react";
import { useTranslation } from "react-i18next";
import { AnimatedNumber } from "@/components/commerce/AnimatedNumber";
import { ChevronDownIcon, KpiIcon } from "@/components/icons";
import { PANEL_WIDTH, REVENUE_TODAY_STALE_MS } from "@/constants/app.constant";
import {
  KPI_BASIS,
  KPI_MISSING,
  onShelfAvailability,
  projectedImpact,
  revenueToday,
  stockoutRisk,
  type KpiBasis,
  type KpiMissing,
} from "@/core/twin/kpiStrip";
import { format } from "@/core/utils/format";
import { useRevenueToday } from "@/hooks/commerce.hook";
import { useAnomalyStore } from "@/state/anomaly.store";
import { usePanelStore } from "@/state/panel.store";
import { useTwinStore } from "@/state/twin.store";
import type { RetailTwinClient } from "@/types/api.type";

/** A signed score move with two decimals, such as "+0.93". */
const signedScore = (value: number) => `${value > 0 ? "+" : ""}${value.toFixed(2)}`;

type TileProps = {
  id: string;
  label: string;
  /** What the tile counts: recorded, Live, or projected. */
  basis: KpiBasis;
  /** The number the tile counts to, animated when it changes; null shows "—". */
  value: number | null;
  /** Why `value` is null. */
  missing?: KpiMissing;
  format: (value: number) => string;
  /** The line under the number. */
  detail: string;
  /** Where the value comes from, or why there is none: the tooltip. */
  hint: string;
  trend?: "up" | "down";
};

/** One tile: a sourced number, or "—" with the reason in its tooltip. Never a 0 for a missing value. */
function KpiTile({ id, label, basis, value, missing, format: fmt, detail, hint, trend }: TileProps) {
  const { t } = useTranslation();
  return (
    <div className="kpi-tile" data-testid={`kpi-${id}`} data-basis={basis} data-missing={value === null ? missing : undefined} title={hint}>
      <span className="kpi-tile-label">{label}</span>
      <strong className="kpi-tile-value" data-trend={value === null ? undefined : trend}>
        {value === null ? "—" : <AnimatedNumber value={value} format={fmt} />}
      </strong>
      <span className="kpi-tile-detail">{value === null ? t("kpiStrip.missing") : detail}</span>
      <span className="sr-only">{hint}</span>
    </div>
  );
}

/**
 * The business KPIs over the 3D view: today's recorded revenue (revenue route), on-shelf
 * availability (Live Twin), open stockouts (anomaly feed) and the impact projected by the KPI
 * evaluator. Each tile shows only what its source served, and "—" with the reason otherwise
 * (missing or stale). The projected tile is set apart in the Simulation colour. Collapsible.
 */
export function KpiStrip({ client }: { client?: RetailTwinClient }) {
  const { t } = useTranslation();
  const [open, setOpen] = useState(true);
  // Never under the open panel at the right.
  const maxWidth = usePanelStore((state) => `calc(100% - ${state.open ? PANEL_WIDTH + 56 : 32}px)`);
  const revenue = revenueToday(useRevenueToday(client), Date.now());
  const availability = onShelfAvailability(useTwinStore((state) => state.live));
  const anomalies = useAnomalyStore((state) => state.anomalies);
  const anomaliesServed = useAnomalyStore((state) => state.served);
  const stockouts = stockoutRisk(anomalies, anomaliesServed);
  const candidates = useTwinStore((state) => state.candidates);
  const hasSimulation = useTwinStore((state) => state.simulation !== null);
  const selectedId = useTwinStore((state) => state.selectedCandidateId);
  const impact = projectedImpact(candidates, hasSimulation, selectedId);

  if (!open) {
    return (
      <button type="button" className="kpi-strip-open" aria-expanded={false} onClick={() => setOpen(true)}>
        <KpiIcon className="h-4 w-4" />
        <span>{t("kpiStrip.title")}</span>
      </button>
    );
  }

  const shelf = availability.value;
  const impactValue = impact.value;
  return (
    <section className="kpi-strip" style={{ maxWidth }} aria-label={t("kpiStrip.title")}>
      <KpiTile
        id="revenue"
        label={t("kpiStrip.revenue.label")}
        basis={KPI_BASIS.Recorded}
        value={revenue.value}
        missing={revenue.reason}
        format={format.money}
        detail={t("kpiStrip.revenue.detail")}
        hint={
          revenue.value !== null
            ? t("kpiStrip.revenue.hint", { value: format.moneyExact(revenue.value) })
            : revenue.reason === KPI_MISSING.Stale
              ? t("kpiStrip.revenue.stale", { minutes: REVENUE_TODAY_STALE_MS / 60_000 })
              : t("kpiStrip.revenue.notServed")
        }
      />
      <KpiTile
        id="availability"
        label={t("kpiStrip.availability.label")}
        basis={KPI_BASIS.Live}
        value={shelf?.share ?? null}
        missing={availability.reason}
        format={format.percent}
        detail={shelf ? t("kpiStrip.availability.detail", { onShelf: shelf.onShelf, total: shelf.total }) : ""}
        hint={
          shelf
            ? t("kpiStrip.availability.hint", { onShelf: shelf.onShelf, total: shelf.total })
            : availability.reason === KPI_MISSING.Empty
              ? t("kpiStrip.availability.empty")
              : t("kpiStrip.availability.notServed")
        }
      />
      <KpiTile
        id="stockout"
        label={t("kpiStrip.stockout.label")}
        basis={KPI_BASIS.Live}
        value={stockouts.value}
        missing={stockouts.reason}
        format={format.count}
        detail={stockouts.value === null ? "" : t("kpiStrip.stockout.detail", { count: stockouts.value })}
        hint={stockouts.value === null ? t("kpiStrip.stockout.notServed") : t("kpiStrip.stockout.hint", { count: stockouts.value })}
      />
      <KpiTile
        id="impact"
        label={t("kpiStrip.impact.label")}
        basis={KPI_BASIS.Projected}
        value={impactValue?.delta ?? null}
        missing={impact.reason}
        format={signedScore}
        detail={impactValue ? t("kpiStrip.impact.detail", { id: impactValue.candidateId }) : ""}
        hint={
          impactValue
            ? t("kpiStrip.impact.hint", {
                id: impactValue.candidateId,
                delta: signedScore(impactValue.delta),
                version: impactValue.evaluatorVersion,
              })
            : impact.reason === KPI_MISSING.NoSimulation
              ? t("kpiStrip.impact.noSimulation")
              : t("kpiStrip.impact.notScored")
        }
        trend={impactValue && impactValue.delta !== 0 ? (impactValue.delta > 0 ? "up" : "down") : undefined}
      />
      <button
        type="button"
        className="kpi-strip-collapse"
        aria-expanded
        aria-label={t("kpiStrip.collapse")}
        title={t("kpiStrip.collapse")}
        onClick={() => setOpen(false)}
      >
        <ChevronDownIcon className="h-4 w-4 rotate-180" />
      </button>
    </section>
  );
}
