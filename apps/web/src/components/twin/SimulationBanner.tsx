import { Button, Tooltip } from "@heroui/react";
import { useTranslation } from "react-i18next";
import { CheckIcon, CloseIcon, SimulationIcon } from "@/components/icons";
import { isNewerVersion } from "@/core/api/version";
import type { SimulationReviewer } from "@/core/twin/simulationReview";
import { ACTION_TYPE, REVIEW_DECISION } from "@/enums/simulation.enum";
import { useShownSimulation } from "@/hooks/activeTwin.hook";
import { useSimulationReview } from "@/hooks/simulationReview.hook";
import { useTwinStore } from "@/state/twin.store";
import type { SimulationAction } from "@/types/simulation.type";

/** One action as the run serves it, so the reviewer sees what Accept would commit. */
function useActionLabel() {
  const { t } = useTranslation();
  return (action: SimulationAction) => {
    switch (action.type) {
      case ACTION_TYPE.MoveProduct:
        return t("simulation.actions.move_product", { sku: action.sku, from: action.from_slot, to: action.to_slot });
      case ACTION_TYPE.ChangeFacings:
        return t("simulation.actions.change_facings", { sku: action.sku, facings: action.facings });
      case ACTION_TYPE.ReplenishShelf:
        return t("simulation.actions.replenish_shelf", { sku: action.sku, quantity: action.quantity });
    }
  };
}

/**
 * While the Simulation view is on: a frame around the 3D view and a label naming the run,
 * the live state it started from, its proposed actions, and that nothing in it has been
 * executed. Says so when Live has moved on since. With a `reviewer`, an evaluated run gets
 * Accept and Reject, which only send the review; see `useSimulationReview`. Renders
 * nothing in the Live view.
 */
export function SimulationBanner({ reviewer = null }: { reviewer?: SimulationReviewer | null }) {
  const { t } = useTranslation();
  const actionLabel = useActionLabel();
  const simulation = useShownSimulation();
  const liveVersion = useTwinStore((state) => state.live?.context_version ?? null);
  const { review, pending, settled, canReview } = useSimulationReview(reviewer, simulation);
  if (!simulation) return null;

  const behind = liveVersion !== null && isNewerVersion(liveVersion, simulation.base_context_version);
  return (
    <>
      <div className="simulation-frame" aria-hidden />
      <div className="simulation-banner" role="status" aria-label={t("simulation.label")}>
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
          {simulation.actions.length ? (
            <ul className="simulation-banner-changes" aria-label={t("simulation.actions.label")}>
              {simulation.actions.map((action, index) => (
                <li key={`${action.type}-${action.sku}-${index}`}>{actionLabel(action)}</li>
              ))}
            </ul>
          ) : null}
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
      </div>
    </>
  );
}
