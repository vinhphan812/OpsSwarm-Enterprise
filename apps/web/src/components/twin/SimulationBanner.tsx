import { Button, Tooltip } from "@heroui/react";
import { useTranslation } from "react-i18next";
import { CheckIcon, CloseIcon, SimulationIcon } from "@/components/icons";
import { isNewerVersion } from "@/core/api/version";
import type { SimulationReviewer } from "@/core/twin/simulationReview";
import { REVIEW_DECISION } from "@/enums/simulation.enum";
import { useProposalAiChanges, useShownSimulation } from "@/hooks/activeTwin.hook";
import { useSimulationReview } from "@/hooks/simulationReview.hook";
import { PANEL_WIDTH } from "@/constants/app.constant";
import { useGuardStore } from "@/state/guard.store";
import { usePanelStore } from "@/state/panel.store";
import { useTwinStore } from "@/state/twin.store";
import { AiChangesList } from "./AiChangesList";
import { CandidatePanel } from "./CandidatePanel";
import { GuardCard } from "./GuardCard";

/** The AI CHANGES of the proposal on screen against Live, outlined in 3D. No KPI values here. */
function ProposalChanges() {
  return <AiChangesList changes={useProposalAiChanges()} />;
}

/**
 * While the Simulation view is on: a frame around the 3D view and a label naming the run,
 * the live state it started from, what it changes (AI CHANGES), and that nothing in it has been
 * executed. Says so when Live has moved on since. With a `reviewer`, an evaluated run gets
 * Accept and Reject, which only send the review; see `useSimulationReview`. Once the run
 * has been approved, the guard's answer shows under it. Renders nothing in the Live view.
 * It stays clear of the Agent Activity panel, beside it or, on a narrow screen, above its
 * bottom sheet, so the panel never covers its controls.
 */
export function SimulationBanner({ reviewer = null }: { reviewer?: SimulationReviewer | null }) {
  const { t } = useTranslation();
  const simulation = useShownSimulation();
  const liveVersion = useTwinStore((state) => state.live?.context_version ?? null);
  const { review, pending, settled, canReview } = useSimulationReview(reviewer, simulation);
  const guardReview = useGuardStore((state) => state.last);
  const panelOpen = usePanelStore((state) => state.open);
  if (!simulation) return null;

  const behind = liveVersion !== null && isNewerVersion(liveVersion, simulation.base_context_version);
  return (
    <>
      <div className="simulation-frame" aria-hidden />
      <div
        className="simulation-banner"
        role="status"
        aria-label={t("simulation.label")}
        data-panel={panelOpen ? "open" : undefined}
        style={{ maxWidth: `min(600px, calc(100% - ${panelOpen ? PANEL_WIDTH + 56 : 32}px))` }}
      >
        <div className="simulation-banner-body">
          <div className="simulation-banner-head">
            <span className="simulation-banner-title">
              <SimulationIcon className="h-4 w-4 shrink-0" />
              {t("simulation.title")}
            </span>
            <span>{t("simulation.notExecuted")}</span>
          </div>
          <span className="simulation-banner-meta">
            {t("simulation.run", { id: simulation.simulation_id, status: t(`simulation.status.${simulation.status}`) })}
            {" · "}
            {t("simulation.basedOn", { version: simulation.base_context_version })}
          </span>
          <ProposalChanges />
          {behind ? <span className="simulation-banner-stale">{t("simulation.liveMoved", { version: liveVersion })}</span> : null}
          {settled ? <span className="simulation-banner-meta">{t("simulation.review.waiting")}</span> : null}
        </div>
        {canReview ? (
          <div className="simulation-banner-actions" role="group" aria-label={t("simulation.review.label")}>
            <Tooltip content={t("simulation.review.rejectHint")} delay={400}>
              <Button
                size="sm"
                variant="bordered"
                className="border-white/15 text-[var(--color-ink)]"
                startContent={pending === REVIEW_DECISION.Reject ? null : <CloseIcon className="h-3.5 w-3.5" />}
                isDisabled={pending !== null}
                isLoading={pending === REVIEW_DECISION.Reject}
                onPress={() => void review(REVIEW_DECISION.Reject)}
              >
                {t("simulation.review.reject")}
              </Button>
            </Tooltip>
            <Tooltip content={t("simulation.review.acceptHint")} delay={400}>
              <Button
                size="sm"
                color="secondary"
                className="font-semibold"
                startContent={pending === REVIEW_DECISION.Approve ? null : <CheckIcon className="h-3.5 w-3.5" />}
                isDisabled={pending !== null}
                isLoading={pending === REVIEW_DECISION.Approve}
                onPress={() => void review(REVIEW_DECISION.Approve)}
              >
                {t("simulation.review.accept")}
              </Button>
            </Tooltip>
          </div>
        ) : null}
        {guardReview?.result.simulation_id === simulation.simulation_id ? (
          <div className="simulation-banner-guard">
            <GuardCard review={guardReview} />
          </div>
        ) : null}
        <CandidatePanel defaultExpanded={false} />
      </div>
    </>
  );
}
