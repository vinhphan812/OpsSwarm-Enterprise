import { VIEW_MODE } from "@/enums/ui.enum";
import { ENTITY_TYPE } from "@/enums/scene.enum";
import { useTwinStore } from "@/state/twin.store";
import { useUiStore } from "@/state/ui.store";
import type { AssistantProposal } from "@/types/assistant.type";

/** Whether `proposal`'s simulation is the open one, so the Simulation view can show it. */
export function proposalOpen(proposal: AssistantProposal, simulationId: string | null | undefined): boolean {
  return simulationId === proposal.simulation_id;
}

/**
 * Shows a Copilot plan in the Simulation view: its candidate (or the run's own proposal),
 * with `sku` (the plan's first product by default) selected, so the camera flies to it.
 * Only shows: approving it stays with the Simulation banner. Nothing when its run is not open.
 */
export function openProposal(proposal: AssistantProposal, sku: string | undefined = proposal.actions[0]?.sku): boolean {
  const twin = useTwinStore.getState();
  if (!proposalOpen(proposal, twin.simulation?.simulation_id)) return false;
  const served = proposal.candidate_id !== null && twin.candidates.some((candidate) => candidate.candidate_id === proposal.candidate_id);
  twin.selectCandidate(served ? proposal.candidate_id : null);
  const ui = useUiStore.getState();
  ui.setViewMode(VIEW_MODE.Simulation);
  if (sku) ui.select(sku, ENTITY_TYPE.Product);
  return true;
}
