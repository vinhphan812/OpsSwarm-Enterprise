import { Modal, ModalBody, ModalContent, ModalHeader } from "@heroui/react";
import { useTranslation } from "react-i18next";
import { compareCandidates } from "@/core/twin/candidateComparison";
import { useImpactStore } from "@/state/impact.store";
import { formatKpiValue, formatNumber } from "./CandidatePanel";

/**
 * The candidates of the approved run, as served at the approval: Current (the baseline) and
 * every proposal, with the accepted one marked. Read only: the run has closed.
 */
export function AiImpactDialog() {
  const { t } = useTranslation();
  const impact = useImpactStore((state) => state.last);
  const open = useImpactStore((state) => state.comparing);
  const setComparing = useImpactStore((state) => state.setComparing);
  if (!impact) return null;
  const { baseline, proposals, rows } = compareCandidates(impact.candidates);
  const accepted = (id: string) => (id === impact.candidate_id ? "selected" : undefined);

  return (
    <Modal isOpen={open} onOpenChange={setComparing} size="2xl" scrollBehavior="inside">
      <ModalContent aria-label={t("impact.compareTitle")}>
        <ModalHeader className="flex flex-col gap-1 pb-2">
          {t("impact.compareTitle")}
          <span className="text-xs font-normal text-ink-muted">
            {t("impact.compareNote", { id: impact.simulation_id, version: impact.evaluator_version })}
          </span>
        </ModalHeader>
        <ModalBody className="pb-5">
          <div className="candidate-table-wrap">
            <table className="candidate-table">
              <thead>
                <tr>
                  <th scope="col">{t("proposal.compare.kpi")}</th>
                  {baseline ? <th scope="col">{t("proposal.compare.current")}</th> : null}
                  {proposals.map(({ candidate_id }) => (
                    <th key={candidate_id} scope="col" className={accepted(candidate_id)}>
                      {candidate_id}
                      {candidate_id === impact.candidate_id ? (
                        <span className="candidate-top">{t("impact.accepted")}</span>
                      ) : null}
                    </th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {rows.map((row) => (
                  <tr key={row.name}>
                    <th scope="row">{t(`proposal.kpi.${row.name}`, { defaultValue: row.name })}</th>
                    {baseline ? (
                      <td>{row.baseline ? formatKpiValue(row.baseline.value, row.baseline.unit) : "—"}</td>
                    ) : null}
                    {proposals.map(({ candidate_id }) => {
                      const cell = row.cells[candidate_id];
                      return (
                        <td key={candidate_id} className={accepted(candidate_id)}>
                          {cell ? (
                            <>
                              <span className="candidate-cell-value">{formatKpiValue(cell.kpi.value, cell.kpi.unit)}</span>
                              {cell.delta !== null ? (
                                <span className="candidate-cell-delta" data-trend={cell.trend}>
                                  {formatNumber(cell.delta, true)}
                                </span>
                              ) : null}
                            </>
                          ) : (
                            "—"
                          )}
                        </td>
                      );
                    })}
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </ModalBody>
      </ModalContent>
    </Modal>
  );
}
