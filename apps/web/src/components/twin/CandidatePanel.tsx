import { Button, Tooltip } from "@heroui/react";
import { useTranslation } from "react-i18next";
import { useState } from "react";
import { CandidateIcon, CheckIcon, ChevronDownIcon } from "@/components/icons";
import { compareCandidates, type KpiCell } from "@/core/twin/candidateComparison";
import { selectedCandidate, useTwinStore } from "@/state/twin.store";
import { useUiStore } from "@/state/ui.store";
import { VIEW_MODE } from "@/enums/ui.enum";
import type { CandidateKPI } from "@/types/simulation.type";
import { DemoBadge } from "./DemoBadge";

/** A served number as written, padded to two decimals: 0.4 is "0.40", 0.125 stays "0.125". */
function formatNumber(value: number, sign = false): string {
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
 * Compares the candidates of the open run (#39): one column per proposal, the served
 * `baseline` as Current, and a row per KPI with each value and its move from Current.
 * Picking a column shows that candidate in the Simulation view (#27). Every value is the
 * one served; the only arithmetic is the display-only difference to the baseline. Says so
 * when there is no baseline, a candidate is not scored, or the last read failed. Renders
 * only in the Simulation view, while the run has candidates. Never writes Live.
 */
export function CandidatePanel() {
  const { t } = useTranslation();
  const viewMode = useUiStore((state) => state.viewMode);
  const twin = useTwinStore();
  const selected = selectedCandidate(twin);
  const { baseline, proposals, rows, topScoreId } = compareCandidates(
    twin.candidates.filter((candidate) => candidate.simulation_id === twin.simulation?.simulation_id),
  );

  if (viewMode !== VIEW_MODE.Simulation || !twin.simulation || !proposals.length) return null;

  const select = (id: string | null) => useTwinStore.getState().selectCandidate(id);
  const label = (kpi: Pick<CandidateKPI, "name">) => t(`proposal.kpi.${kpi.name}`, { defaultValue: kpi.name });
  const columnClass = (id: string) => (id === selected?.candidate_id ? "selected" : undefined);
  const evaluators = [...new Set(proposals.map((candidate) => candidate.evaluator_version))].join(", ");

  return (
    <div className="candidate-panel" role="region" aria-label={t("proposal.compare.label")}>
      <div className="candidate-panel-header">
        <span className="candidate-panel-title">
          <CandidateIcon className="h-4 w-4 shrink-0" />
          {t("proposal.compare.title")}
          <DemoBadge />
        </span>
        <span className="candidate-panel-meta">{t("proposal.compare.evaluator", { version: evaluators })}</span>
      </div>

      {twin.simulationReadFailed ? (
        <p className="candidate-panel-note warning" role="alert">{t("proposal.compare.readFailed")}</p>
      ) : null}
      {baseline ? null : <p className="candidate-panel-note">{t("proposal.compare.noBaseline")}</p>}

      <div className="candidate-table-wrap">
        <table className="candidate-table">
          <thead>
            <tr>
              <th scope="col">{t("proposal.compare.kpi")}</th>
              {baseline ? <th scope="col">{t("proposal.compare.current")}</th> : null}
              {proposals.map(({ candidate_id }) => (
                <th key={candidate_id} scope="col" className={columnClass(candidate_id)}>
                  <Tooltip content={t("proposal.candidate.switchHint", { id: candidate_id })} delay={300}>
                    <button
                      type="button"
                      className="candidate-column-btn"
                      aria-pressed={candidate_id === selected?.candidate_id}
                      onClick={() => select(candidate_id)}
                    >
                      {candidate_id === selected?.candidate_id ? <CheckIcon className="h-3 w-3" /> : null}
                      {candidate_id}
                    </button>
                  </Tooltip>
                  {candidate_id === topScoreId ? <span className="candidate-top">{t("proposal.compare.topScore")}</span> : null}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            <tr>
              <th scope="row">{t("proposal.compare.actions")}</th>
              {baseline ? <td>{baseline.proposed_actions.length}</td> : null}
              {proposals.map((candidate) => (
                <td key={candidate.candidate_id} className={columnClass(candidate.candidate_id)}>
                  {candidate.proposed_actions.length}
                </td>
              ))}
            </tr>
            {rows.map((row) => (
              <tr key={row.name}>
                <th scope="row">{label(row)}</th>
                {baseline ? <td>{row.baseline ? formatKpiValue(row.baseline.value, row.baseline.unit) : "—"}</td> : null}
                {proposals.map((candidate) => (
                  <td key={candidate.candidate_id} className={columnClass(candidate.candidate_id)}>
                    <KpiValue cell={row.cells[candidate.candidate_id]} scored={candidate.kpis.length > 0} />
                  </td>
                ))}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      {rows.length ? (
        baseline ? <p className="candidate-panel-meta">{t("proposal.compare.deltaNote")}</p> : null
      ) : (
        <span className="candidate-panel-no-kpis">{t("proposal.candidate.noKpis")}</span>
      )}

      {selected ? <ProvenanceSection text={selected.provenance} /> : null}

      <div className="candidate-selector">
        <Tooltip content={t("proposal.candidate.showSimulation")} delay={300}>
          <Button
            size="sm"
            variant={selected ? "light" : "bordered"}
            className={`candidate-selector-btn simulation-btn${selected ? "" : " active"}`}
            onPress={() => select(null)}
            aria-pressed={selected === null}
          >
            {t("proposal.candidate.simulationProposal")}
          </Button>
        </Tooltip>
        <span className="candidate-panel-meta">
          {selected ? t("proposal.compare.showing", { id: selected.candidate_id }) : t("proposal.compare.pick")}
        </span>
      </div>
    </div>
  );
}
