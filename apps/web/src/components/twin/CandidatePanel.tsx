import { Button, Tooltip } from "@heroui/react";
import { useTranslation } from "react-i18next";
import { useState } from "react";
import { CandidateIcon, CheckIcon, ChevronDownIcon, KpiIcon } from "@/components/icons";
import { selectedCandidate, useTwinStore } from "@/state/twin.store";
import { useUiStore } from "@/state/ui.store";
import { VIEW_MODE } from "@/enums/ui.enum";

/** Format a KPI value with its unit, e.g. "$1,240.50". */
function formatKpiValue(value: number, unit: string): string {
  if (unit === "$") {
    return `${unit}${value.toLocaleString("en-US", { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`;
  }
  if (unit === "%") {
    return `${value.toFixed(1)}${unit}`;
  }
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

/** Shows the selected candidate's KPI scores and provenance. Only renders when a
 * candidate is selected (not the simulation's own proposal) and the Simulation view is active.
 * Keeps simulation state strictly isolated from live state — all data comes from the candidate,
 * never writes back.
 */
export function CandidatePanel() {
  const { t } = useTranslation();
  const viewMode = useUiStore((state) => state.viewMode);
  const twin = useTwinStore();
  const candidate = selectedCandidate(twin);
  const candidates = useTwinStore((s) => s.candidates);
  const selectedId = useTwinStore((s) => s.selectedCandidateId);

  // Only show in the Simulation view and only when a candidate is selected.
  if (viewMode !== VIEW_MODE.Simulation || !candidate) return null;

  return (
    <div className="candidate-panel" role="region" aria-label={t("proposal.candidate.label")}>
      <div className="candidate-panel-header">
        <span className="candidate-panel-title">
          <CandidateIcon className="h-4 w-4 shrink-0" />
          {t("proposal.candidate.title", { id: candidate.candidate_id })}
        </span>
        {candidate.kpis.length > 0 ? (
          <div className="candidate-panel-kpis" role="list" aria-label={t("proposal.candidate.kpis")}>
            <div className="candidate-kpi-grid">
              {candidate.kpis.map((kpi) => (
                <div key={kpi.name} className="candidate-kpi-cell" role="listitem">
                  <KpiIcon className="candidate-kpi-icon" />
                  <span className="candidate-kpi-name">{kpi.name}</span>
                  <span className="candidate-kpi-value">{formatKpiValue(kpi.value, kpi.unit)}</span>
                </div>
              ))}
            </div>
          </div>
        ) : (
          <span className="candidate-panel-no-kpis">{t("proposal.candidate.noKpis")}</span>
        )}
      </div>

      <ProvenanceSection text={candidate.provenance} />

      <div className="candidate-selector" role="group" aria-label={t("proposal.candidate.selector")}>
        {candidates.map((c) => (
          <Tooltip key={c.candidate_id} content={t("proposal.candidate.switchHint", { id: c.candidate_id })} delay={300}>
            <Button
              size="sm"
              variant={c.candidate_id === selectedId ? "solid" : "bordered"}
              className={`candidate-selector-btn${c.candidate_id === selectedId ? " active" : ""}`}
              onPress={() => void useTwinStore.getState().selectCandidate(c.candidate_id)}
              aria-pressed={c.candidate_id === selectedId}
            >
              {c.candidate_id === selectedId ? (
                <CheckIcon className="h-3 w-3" />
              ) : null}
              {c.candidate_id}
            </Button>
          </Tooltip>
        ))}
        <Tooltip content={t("proposal.candidate.showSimulation")} delay={300}>
          <Button
            size="sm"
            variant="light"
            className="candidate-selector-btn simulation-btn"
            onPress={() => void useTwinStore.getState().selectCandidate(null)}
            aria-pressed={selectedId === null}
          >
            {t("proposal.candidate.simulationProposal")}
          </Button>
        </Tooltip>
      </div>
    </div>
  );
}
