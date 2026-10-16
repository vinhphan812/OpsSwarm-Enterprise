import { useTranslation } from "react-i18next";
import type { AiImpact, ImpactRow } from "@/core/twin/aiImpact";
import type { ActivityEntry } from "@/types/agent.type";
import { useImpactStore } from "@/state/impact.store";
import { formatKpiValue, formatNumber } from "./CandidatePanel";

/** One KPI as "before → after" and its move, each value as served. */
export function ImpactRowView({ row }: { row: ImpactRow }) {
  const { t } = useTranslation();
  const delta = formatNumber(row.delta, true);
  return (
    <li className="impact-row">
      <span className="impact-kpi">{t(`proposal.kpi.${row.name}`, { defaultValue: row.name })}</span>
      <span className="impact-values">
        <span className="impact-before">{formatKpiValue(row.before.value, row.before.unit)}</span>
        <span aria-hidden="true">→</span>
        <span className="impact-after">{formatKpiValue(row.after.value, row.after.unit)}</span>
      </span>
      <span
        className="impact-delta"
        data-trend={row.trend}
        aria-label={t("impact.delta", { delta, trend: t(`proposal.compare.trend.${row.trend}`) })}
      >
        {delta}
      </span>
    </li>
  );
}

/** Opens the comparison of the run's candidates, as served at the approval. */
export function CompareButton() {
  const { t } = useTranslation();
  const setComparing = useImpactStore((state) => state.setComparing);
  return (
    <button type="button" className="impact-compare" onClick={() => setComparing(true)}>
      {t("impact.compare")}
    </button>
  );
}

/**
 * What the verifier reported for the run, as served on its VERIFY entry. Shown apart from
 * the projection: a VERIFY entry is not a measurement of the projected KPIs.
 */
export function VerifierStatus({ verify }: { verify: ActivityEntry }) {
  const { t } = useTranslation();
  const status = verify.status
    ? t(`impact.verifier.${verify.status}`, { defaultValue: verify.status })
    : t("impact.verifier.unknown");
  return (
    <p className="impact-verifier" data-status={verify.status ?? "unknown"}>
      {t("impact.verifier.label", { status })}
    </p>
  );
}

/**
 * The projected impact of an executed approval: each KPI of the baseline next to the
 * accepted candidate's, as the evaluator simulated them, and the verifier's status apart.
 * Every value is the evaluator's projection, never an observed post-action KPI.
 */
export function AiImpactCard({ impact, verify }: { impact: AiImpact; verify: ActivityEntry }) {
  const { t } = useTranslation();
  return (
    <div className="impact-card" data-testid="ai-impact" role="region" aria-label={t("impact.title")}>
      <div className="impact-head">
        <span className="impact-title">{t("impact.title")}</span>
        <span className="impact-plan">{t("impact.plan", { id: impact.candidate_id })}</span>
      </div>
      <div className="impact-columns" aria-hidden="true">
        <span>{t("impact.before")}</span>
        <span>{t("impact.after")}</span>
      </div>
      <ul className="impact-rows">
        {impact.rows.map((row) => (
          <ImpactRowView key={row.name} row={row} />
        ))}
      </ul>
      <div className="impact-foot">
        <span className="impact-note">{t("impact.note", { version: impact.evaluator_version })}</span>
        <CompareButton />
      </div>
      <VerifierStatus verify={verify} />
    </div>
  );
}
