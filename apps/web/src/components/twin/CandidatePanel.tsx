import { Tooltip } from "@heroui/react";
import { useTranslation } from "react-i18next";
import { useId, useState } from "react";
import { CandidateIcon, ChevronDownIcon } from "@/components/icons";
import { compareCandidates, planLetter, type KpiCell } from "@/core/twin/candidateComparison";
import { selectedCandidate, useTwinStore } from "@/state/twin.store";
import { useUiStore } from "@/state/ui.store";
import { KPI_NAME } from "@/enums/simulation.enum";
import { VIEW_MODE } from "@/enums/ui.enum";
import type { CandidateKPI } from "@/types/simulation.type";
import { DemoBadge } from "./DemoBadge";

/** A served number as written, padded to two decimals: 0.4 is "0.40", 0.125 stays "0.125". */
export function formatNumber(value: number, sign = false): string {
  const text = value.toLocaleString("en-US", { minimumFractionDigits: 2, maximumFractionDigits: 10 });
  return sign && value > 0 ? `+${text}` : text;
}

/** A KPI value with its unit, e.g. "$1,240.50", "12.0%", or "0.27" for a share of demand. */
export function formatKpiValue(value: number, unit: string): string {
  if (unit === "$") {
    return `${unit}${value.toLocaleString("en-US", { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`;
  }
  if (unit === "%") {
    return `${value.toFixed(1)}${unit}`;
  }
  if (unit === "share") return formatNumber(value);
  return `${value} ${unit}`;
}

/** The provenance section of a candidate, collapsible to keep it out of the way. */
function ProvenanceSection({ text }: { text: string }) {
  const { t } = useTranslation();
  const [expanded, setExpanded] = useState(false);
  return (
    <div className="candidate-justification">
      <button
        type="button"
        className="candidate-justification-toggle"
        onClick={() => setExpanded((e) => !e)}
        aria-expanded={expanded}
      >
        <span>{t("proposal.candidate.provenance")}</span>
        <ChevronDownIcon className={`candidate-justification-chevron${expanded ? " expanded" : ""}`} />
      </button>
      {expanded ? <p className="candidate-justification-text">{text}</p> : null}
    </div>
  );
}

/** A candidate's value of one KPI, and its move from the baseline when one is served. */
function KpiValue({ cell, scored }: { cell: KpiCell | undefined; scored: boolean }) {
  const { t } = useTranslation();
  if (!cell) return <span className="candidate-cell-missing">{scored ? "—" : t("proposal.compare.notScored")}</span>;
  const { kpi, delta, trend } = cell;
  return (
    <>
      <span className="candidate-cell-value">{formatKpiValue(kpi.value, kpi.unit)}</span>
      {delta !== null && trend !== null ? (
        <span
          className="candidate-cell-delta"
          data-trend={trend}
          aria-label={t("proposal.compare.delta", { delta: formatNumber(delta, true), trend: t(`proposal.compare.trend.${trend}`) })}
        >
          {formatNumber(delta, true)}
        </span>
      ) : null}
    </>
  );
}

/**
 * The lead plan in one line, for the folded panel: the plan the agent recommends (or, with
 * none served, the top served business score), its business score and its move from Current.
 */
function LeadPlan({ plan, badge, cell, scored }: { plan: string; badge: string; cell: KpiCell | undefined; scored: boolean }) {
  const { t } = useTranslation();
  return (
    <p className="candidate-lead">
      <CandidateIcon className="candidate-star" />
      <strong>{plan}</strong>
      <span className="candidate-badge recommended">{badge}</span>
      <span className="candidate-lead-score">
        {t("proposal.kpi.business_score")} <KpiValue cell={cell} scored={scored} />
      </span>
    </p>
  );
}

/**
 * Compares the candidates of the open run (#39): one column per proposal, labelled Plan A,
 * B, C in served order, the served `baseline` as Current, and a row per KPI, the business
 * score first, with each value and its move from Current. The plan the agent recommends
 * (`recommended`) is starred, with its rationale under the table when one is served (#207);
 * with none served, the highest served business score is marked instead. Picking a column
 * shows that candidate in the Simulation view (#27). Every value is the one served; the only
 * arithmetic is the display-only difference to the baseline. Says so when there is no
 * baseline, a candidate is not scored, or the last read failed. Renders only in the
 * Simulation view, while the run has candidates. Never writes Live.
 * Folded (`defaultExpanded={false}`, as in the simulation banner), it shows only the lead
 * plan, its rationale and the plan on screen, and "Compare plans" opens the table, so the
 * banner fits the view without a scroll of its own.
 */
export function CandidatePanel({ defaultExpanded = true }: { defaultExpanded?: boolean }) {
  const { t } = useTranslation();
  const [expanded, setExpanded] = useState(defaultExpanded);
  const tableId = useId();
  const viewMode = useUiStore((state) => state.viewMode);
  const twin = useTwinStore();
  const selected = selectedCandidate(twin);
  const { baseline, proposals, rows, topScoreId, recommendedId } = compareCandidates(
    twin.candidates.filter((candidate) => candidate.simulation_id === twin.simulation?.simulation_id),
  );

  if (viewMode !== VIEW_MODE.Simulation || !twin.simulation || !proposals.length) return null;

  const select = (id: string | null) => useTwinStore.getState().selectCandidate(id);
  const label = (kpi: Pick<CandidateKPI, "name">) => t(`proposal.kpi.${kpi.name}`, { defaultValue: kpi.name });
  const plans = new Map(proposals.map(({ candidate_id }, index) => [candidate_id, t("proposal.compare.plan", { letter: planLetter(index) })]));
  const planOf = (id: string) => plans.get(id) ?? id;
  const columnClass = (id: string) =>
    [id === selected?.candidate_id ? "selected" : "", id === recommendedId ? "recommended" : ""].filter(Boolean).join(" ") || undefined;
  const evaluators = [...new Set(proposals.map((candidate) => candidate.evaluator_version))].join(", ");
  const recommended = proposals.find((candidate) => candidate.candidate_id === recommendedId);
  const lead = recommended ?? proposals.find((candidate) => candidate.candidate_id === topScoreId);
  const scoreRow = rows.find((row) => row.name === KPI_NAME.BusinessScore);

  return (
    <div className="candidate-panel" role="region" aria-label={t("proposal.compare.label")}>
      <div className="candidate-panel-header">
        <span className="candidate-panel-title">
          {t("proposal.compare.title")}
          <DemoBadge />
        </span>
        {expanded ? <span className="candidate-panel-meta">{t("proposal.compare.evaluator", { version: evaluators })}</span> : null}
        <button
          type="button"
          className="candidate-panel-toggle"
          aria-expanded={expanded}
          aria-controls={tableId}
          onClick={() => setExpanded((open) => !open)}
        >
          {t(expanded ? "proposal.compare.collapse" : "proposal.compare.expand")}
          <ChevronDownIcon className={`candidate-justification-chevron${expanded ? " expanded" : ""}`} />
        </button>
      </div>

      {twin.simulationReadFailed ? (
        <p className="candidate-panel-note warning" role="alert">{t("proposal.compare.readFailed")}</p>
      ) : null}
      {!expanded && lead ? (
        <LeadPlan
          plan={planOf(lead.candidate_id)}
          badge={t(recommended ? "proposal.compare.recommended" : "proposal.compare.topScore")}
          cell={scoreRow?.cells[lead.candidate_id]}
          scored={lead.kpis.length > 0}
        />
      ) : null}
      {expanded ? (
        <>
          {baseline ? null : <p className="candidate-panel-note">{t("proposal.compare.noBaseline")}</p>}

          <div className="candidate-table-wrap" id={tableId}>
            <table className="candidate-table">
              <thead>
                <tr>
                  <th scope="col">
                    <span className="sr-only">{t("proposal.compare.kpi")}</span>
                  </th>
                  {baseline ? <th scope="col" className="candidate-current">{t("proposal.compare.current")}</th> : null}
                  {proposals.map(({ candidate_id }) => (
                    <th key={candidate_id} scope="col" className={columnClass(candidate_id)}>
                      <Tooltip content={t("proposal.candidate.switchHint", { id: candidate_id })} delay={300}>
                        <button
                          type="button"
                          className="candidate-column-btn"
                          aria-pressed={candidate_id === selected?.candidate_id}
                          onClick={() => select(candidate_id)}
                        >
                          {candidate_id === recommendedId ? <CandidateIcon className="candidate-star" /> : null}
                          {planOf(candidate_id)}
                        </button>
                      </Tooltip>
                      {candidate_id === recommendedId ? (
                        <span className="candidate-badge recommended">{t("proposal.compare.recommended")}</span>
                      ) : candidate_id === topScoreId && !recommendedId ? (
                        <span className="candidate-badge">{t("proposal.compare.topScore")}</span>
                      ) : null}
                    </th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {rows.map((row) => (
                  <tr key={row.name} className={row.name === KPI_NAME.BusinessScore ? "candidate-score-row" : undefined}>
                    <th scope="row">{label(row)}</th>
                    {baseline ? (
                      <td className="candidate-current">{row.baseline ? formatKpiValue(row.baseline.value, row.baseline.unit) : "—"}</td>
                    ) : null}
                    {proposals.map((candidate) => (
                      <td key={candidate.candidate_id} className={columnClass(candidate.candidate_id)}>
                        <KpiValue cell={row.cells[candidate.candidate_id]} scored={candidate.kpis.length > 0} />
                      </td>
                    ))}
                  </tr>
                ))}
                <tr>
                  <th scope="row">{t("proposal.compare.actions")}</th>
                  {baseline ? <td className="candidate-current">{baseline.proposed_actions.length}</td> : null}
                  {proposals.map((candidate) => (
                    <td key={candidate.candidate_id} className={columnClass(candidate.candidate_id)}>
                      {candidate.proposed_actions.length}
                    </td>
                  ))}
                </tr>
              </tbody>
            </table>
          </div>
          {rows.length ? (
            baseline ? <p className="candidate-panel-meta candidate-delta-note">{t("proposal.compare.deltaNote")}</p> : null
          ) : (
            <span className="candidate-panel-no-kpis">{t("proposal.candidate.noKpis")}</span>
          )}
        </>
      ) : null}

      {recommended?.rationale ? (
        <p className="candidate-rationale">
          <CandidateIcon className="candidate-star" />
          <span>
            <strong>{t("proposal.compare.whyChose", { plan: planOf(recommended.candidate_id) })}</strong> {recommended.rationale}
          </span>
        </p>
      ) : null}

      {expanded && selected ? <ProvenanceSection text={selected.provenance} /> : null}

      {expanded || selected ? (
        <div className="candidate-selector">
          <span className="candidate-panel-meta">
            {selected ? t("proposal.compare.showing", { plan: planOf(selected.candidate_id) }) : t("proposal.compare.pick")}
          </span>
          {selected ? (
            <Tooltip content={t("proposal.candidate.showSimulation")} delay={300}>
              <button type="button" className="candidate-back" onClick={() => select(null)}>
                {t("proposal.candidate.simulationProposal")}
              </button>
            </Tooltip>
          ) : null}
        </div>
      ) : null}
    </div>
  );
}
