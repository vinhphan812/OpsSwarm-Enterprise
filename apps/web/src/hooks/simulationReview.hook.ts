import { useState } from "react";
import { useTranslation } from "react-i18next";
import { notify } from "@/core/notify";
import { impactOf } from "@/core/twin/aiImpact";
import type { SimulationReviewer } from "@/core/twin/simulationReview";
import {
  GUARD_VERDICT,
  REVIEW_DECISION,
  REVIEW_REASON,
  SIMULATION_STATUS,
  type ReviewDecision,
} from "@/enums/simulation.enum";
import { VIEW_MODE } from "@/enums/ui.enum";
import { useGuardStore } from "@/state/guard.store";
import { useImpactStore } from "@/state/impact.store";
import { selectedCandidate, useTwinStore } from "@/state/twin.store";
import { useUiStore } from "@/state/ui.store";
import type { ReviewResult, Simulation } from "@/types/simulation.type";

/** One proposal of one run: what a review was about. */
const reviewKey = (simulation: Simulation) => `${simulation.simulation_id}@${simulation.state.context_version}`;

/**
 * Accept and Reject for the simulation on screen. A review only asks: the twin state on
 * screen changes when the live feed and the simulation feed say so, never here. An
 * evaluated run can be reviewed once; after a committed or rejected answer it waits for
 * the run to close. A review is of one proposal (`state.context_version`), so a proposal
 * replaced under the same run id can be reviewed again. The guard's answer to an approval
 * is kept in `useGuardStore` for the guard card. An executed approval records its AI
 * Impact: the accepted candidate's KPIs against the baseline's, or none without a candidate.
 */
export function useSimulationReview(reviewer: SimulationReviewer | null, simulation: Simulation | null) {
  const { t } = useTranslation();
  const [pending, setPending] = useState<ReviewDecision | null>(null);
  const [settledKey, setSettledKey] = useState<string | null>(null);

  const announce = (result: ReviewResult, base: string) => {
    const id = result.simulation_id;
    const reason = result.reason_code
      ? t(`guard.reason.${result.reason_code}`, { defaultValue: result.reason_code })
      : t("simulation.review.noReason");
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
    // What was on screen when the review was sent: the run closes once it is committed.
    const twin = useTwinStore.getState();
    const candidateId = selectedCandidate(twin)?.candidate_id ?? null;
    const candidates = twin.candidates;
    try {
      const result = await reviewer(simulation, decision);
      announce(result, simulation.base_context_version);
      if (result.decision === REVIEW_DECISION.Approve) {
        useGuardStore.getState().record({ result, base_context_version: simulation.base_context_version });
      }
      if (result.verdict === GUARD_VERDICT.Allow && result.status === SIMULATION_STATUS.Committed) {
        useImpactStore.getState().record(impactOf(candidates, simulation.simulation_id, candidateId));
      }
      // The rejected proposal leaves the screen; its changes go back to Live in 3D.
      if (result.status === SIMULATION_STATUS.Rejected && useUiStore.getState().viewMode === VIEW_MODE.Simulation) {
        useTwinStore.getState().leaveProposal(simulation.state);
      }
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
