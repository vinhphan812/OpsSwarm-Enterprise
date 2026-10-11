import { useState } from "react";
import { useTranslation } from "react-i18next";
import { notify } from "@/core/notify";
import type { SimulationReviewer } from "@/core/twin/simulationReview";
import {
  GUARD_VERDICT,
  REVIEW_DECISION,
  REVIEW_REASON,
  SIMULATION_STATUS,
  type ReviewDecision,
} from "@/enums/simulation.enum";
import type { ReviewResult, Simulation } from "@/types/simulation.type";

/** One proposal of one run: what a review was about. */
const reviewKey = (simulation: Simulation) => `${simulation.simulation_id}@${simulation.state.context_version}`;

/**
 * Accept and Reject for the simulation on screen. A review only asks: the twin state on
 * screen changes when the live feed and the simulation feed say so, never here. An
 * evaluated run can be reviewed once; after a committed or rejected answer it waits for
 * the run to close. A review is of one proposal (`state.context_version`), so a proposal
 * replaced under the same run id can be reviewed again.
 */
export function useSimulationReview(reviewer: SimulationReviewer | null, simulation: Simulation | null) {
  const { t } = useTranslation();
  const [pending, setPending] = useState<ReviewDecision | null>(null);
  const [settledKey, setSettledKey] = useState<string | null>(null);

  const announce = (result: ReviewResult, base: string) => {
    const id = result.simulation_id;
    const reason = result.reason_code ?? t("simulation.review.noReason");
    const proposalChanged = result.reason_code === REVIEW_REASON.ProposalChanged;
    if (result.decision === REVIEW_DECISION.Reject) {
      if (result.status !== SIMULATION_STATUS.Rejected) {
        notify.warning(
          t("simulation.review.rejectRefused", { id }),
          proposalChanged ? t("simulation.review.proposalChangedHint") : reason,
        );
        return;
      }
      notify.info(t("simulation.review.rejected", { id }), t("simulation.review.liveUnchanged"));
      return;
    }
    switch (result.verdict) {
      case GUARD_VERDICT.Allow:
        notify.success(
          t("simulation.review.approved", { id }),
          result.live_context_version
            ? t("simulation.review.committed", { version: result.live_context_version })
            : t("simulation.review.executing"),
        );
        return;
      case GUARD_VERDICT.RefreshRequired:
        notify.warning(
          t("simulation.review.refresh", { id }),
          proposalChanged ? t("simulation.review.proposalChangedHint") : t("simulation.review.refreshHint", { base }),
        );
        return;
      case GUARD_VERDICT.Deny:
        notify.warning(t("simulation.review.denied", { id }), reason);
        return;
      default:
        notify.info(t("simulation.review.humanReview", { id }), reason);
    }
  };

  const review = async (decision: ReviewDecision) => {
    if (!reviewer || !simulation || pending) return;
    setPending(decision);
    try {
      const result = await reviewer(simulation, decision);
      announce(result, simulation.base_context_version);
      if (result.status === SIMULATION_STATUS.Committed || result.status === SIMULATION_STATUS.Rejected) {
        setSettledKey(reviewKey(simulation));
      }
    } catch (error) {
      notify.error(t("simulation.review.failed"), error);
    } finally {
      setPending(null);
    }
  };

  const settled = simulation !== null && settledKey === reviewKey(simulation);
  return {
    review,
    pending,
    settled,
    /** Accept and Reject show only for an evaluated run, while something can take the review. */
    canReview: reviewer !== null && simulation?.status === SIMULATION_STATUS.Evaluated && !settled,
  };
}
