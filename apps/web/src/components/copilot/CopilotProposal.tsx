import { Button } from "@heroui/react";
import { useRef } from "react";
import { useTranslation } from "react-i18next";
import { CheckIcon, CloseIcon, ShieldIcon, SimulationIcon } from "@/components/icons";
import { formatKpiValue, formatNumber } from "@/components/twin/CandidatePanel";
import { openProposal, proposalOpen } from "@/core/assistant/openProposal";
import { actionLabel } from "@/core/assistant/proposalText";
import { isNewerVersion } from "@/core/api/version";
import { kpiDelta, kpiTrend } from "@/core/twin/candidateComparison";
import { KPI_NAME, SIMULATION_STATUS } from "@/enums/simulation.enum";
import { useGuardStore } from "@/state/guard.store";
import { useTwinStore } from "@/state/twin.store";
import type { AssistantProposal } from "@/types/assistant.type";
import type { CandidateKPI } from "@/types/simulation.type";

/** The business score first, as the candidate panel ranks plans by it; the rest as served. */
function ordered(kpis: CandidateKPI[]): CandidateKPI[] {
  const score = kpis.find((kpi) => kpi.name === KPI_NAME.BusinessScore);
  return score ? [score, ...kpis.filter((kpi) => kpi !== score)] : kpis;
}

/** The plan's KPIs, each against the baseline's when one is served. Values as served; never computed here. */
function ProposalKpis({ proposal }: { proposal: AssistantProposal }) {
  const { t } = useTranslation();
  if (!proposal.kpis.length) return <p className="copilot-proposal-muted">{t("copilot.proposal.notScored")}</p>;
  return (
    <div className="copilot-proposal-kpis">
      <table aria-label={t("copilot.proposal.kpis")}>
        <tbody>
          {ordered(proposal.kpis).map((kpi) => {
            const before = proposal.baseline_kpis.find((item) => item.name === kpi.name);
            const delta = before ? kpiDelta(kpi.value, before.value) : null;
            return (
              <tr key={kpi.name}>
                <th scope="row">{t(`proposal.kpi.${kpi.name}`, { defaultValue: kpi.name })}</th>
                <td>{before ? formatKpiValue(before.value, before.unit) : "—"}</td>
                <td aria-hidden>→</td>
                <td className="copilot-proposal-kpi-value">{formatKpiValue(kpi.value, kpi.unit)}</td>
                <td className="candidate-cell-delta" data-trend={delta === null ? undefined : kpiTrend(kpi.name, delta)}>
                  {delta === null ? "" : formatNumber(delta, true)}
                </td>
              </tr>
            );
          })}
        </tbody>
      </table>
      {proposal.evaluator_version ? (
        <p className="copilot-proposal-muted">{t("copilot.proposal.evaluator", { version: proposal.evaluator_version })}</p>
      ) : null}
    </div>
  );
}

/** Where the guard stands on the plan: its answer to an Accept, a pre-check apps/api ran, or not yet asked. */
function GuardLine({ proposal }: { proposal: AssistantProposal }) {
  const { t } = useTranslation();
  const last = useGuardStore((state) => state.last);
  const reviewed = last?.result.simulation_id === proposal.simulation_id ? last.result : null;
  const text = reviewed?.verdict
    ? t("copilot.proposal.guardLast", { verdict: t(`guard.verdict.${reviewed.verdict}`) })
    : proposal.guard
      ? t("copilot.proposal.guardPrecheck", { verdict: t(`guard.verdict.${proposal.guard.verdict}`) })
      : t("copilot.proposal.guardPending");
  return (
    <p className="copilot-proposal-guard">
      <ShieldIcon className="h-3.5 w-3.5 shrink-0" />
      {text}
    </p>
  );
}

/**
 * A plan the Copilot opened as a simulation: its actions, its KPIs against the baseline, the
 * checks it was held to and the guard's word on it. "Review in Simulation" shows it in 3D;
 * Accept and Reject stay with the Simulation banner and its guarded review, never here.
 * Until its run is the open one, it says it is waiting for it; once that run closes, that it has.
 */
export function CopilotProposal({ proposal }: { proposal: AssistantProposal }) {
  const { t } = useTranslation();
  const openId = useTwinStore((state) => state.simulation?.simulation_id ?? null);
  const liveVersion = useTwinStore((state) => state.live?.context_version ?? null);
  const last = useGuardStore((state) => state.last);
  const open = proposalOpen(proposal, openId);
  // A run apps/api has just opened shows up with the next simulation read; one that was open has closed since.
  const seenOpen = useRef(open);
  if (open) seenOpen.current = true;
  const stale = open && liveVersion !== null && isNewerVersion(liveVersion, proposal.base_context_version);
  const committed =
    last?.result.simulation_id === proposal.simulation_id && last.result.status === SIMULATION_STATUS.Committed ? last.result : null;

  return (
    <section className="copilot-proposal" aria-label={t("copilot.proposal.title")}>
      <header className="copilot-proposal-head">
        <SimulationIcon className="h-4 w-4 shrink-0" />
        <span className="copilot-proposal-title">{t("copilot.proposal.title")}</span>
        <span className="copilot-proposal-run">
          {t("copilot.proposal.run", { id: proposal.simulation_id, version: proposal.base_context_version })}
        </span>
      </header>
      <ul className="copilot-proposal-actions" aria-label={t("copilot.proposal.actions")}>
        {proposal.actions.map((action, index) => {
          const label = actionLabel(action);
          return (
            <li key={`${action.type}:${action.sku}:${index}`}>
              <button
                type="button"
                disabled={!open}
                aria-label={t("copilot.proposal.actionHint", { action: label })}
                onClick={() => openProposal(proposal, action.sku)}
              >
                {label}
              </button>
            </li>
          );
        })}
      </ul>
      <ProposalKpis proposal={proposal} />
      {proposal.constraints.length ? (
        <ul className="copilot-proposal-checks" aria-label={t("copilot.proposal.constraints")}>
          {proposal.constraints.map((check) => (
            <li key={check.label} data-passed={check.passed}>
              {check.passed ? <CheckIcon className="h-3.5 w-3.5 shrink-0" /> : <CloseIcon className="h-3.5 w-3.5 shrink-0" />}
              <span>{check.label}</span>
              <span className="sr-only">{t(check.passed ? "copilot.proposal.passed" : "copilot.proposal.failed")}</span>
            </li>
          ))}
        </ul>
      ) : null}
      <GuardLine proposal={proposal} />
      {stale ? <p className="copilot-proposal-stale">{t("copilot.proposal.stale", { version: liveVersion })}</p> : null}
      {open ? (
        <>
          <Button
            size="sm"
            color="secondary"
            className="w-full font-semibold"
            startContent={<SimulationIcon className="h-3.5 w-3.5" />}
            title={t("copilot.proposal.reviewHint")}
            onPress={() => openProposal(proposal)}
          >
            {t("copilot.proposal.review")}
          </Button>
          <p className="copilot-proposal-muted">{t("copilot.proposal.approveNote")}</p>
        </>
      ) : (
        <p className="copilot-proposal-muted">
          {committed?.live_context_version
            ? t("copilot.proposal.committed", { version: committed.live_context_version })
            : seenOpen.current
              ? t("copilot.proposal.closed")
              : t("copilot.proposal.waiting", { id: proposal.simulation_id })}
        </p>
      )}
    </section>
  );
}
