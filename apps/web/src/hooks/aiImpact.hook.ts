import type { AgentRun } from "@/core/agent/agentRuns";
import type { AiChanges } from "@/core/twin/aiChanges";
import { runVerify, type AiImpact } from "@/core/twin/aiImpact";
import { useImpactStore } from "@/state/impact.store";
import { useRunStore } from "@/state/run.store";
import type { ActivityEntry } from "@/types/agent.type";

/** The last projected impact and its run's VERIFY entry, once an agent run of its simulation has reached VERIFY; else null. */
export function useVerifiedImpact(): { impact: AiImpact; verify: ActivityEntry } | null {
  const impact = useImpactStore((state) => state.last);
  const verify = useRunStore((state) => (impact ? runVerify(state.activity, impact.simulation_id) : null));
  return impact && verify ? { impact, verify } : null;
}

/** The verified impact when its VERIFY entry is `run`'s own; else null. */
export function useRunImpact(run: AgentRun): { impact: AiImpact; verify: ActivityEntry } | null {
  const verified = useVerifiedImpact();
  return verified?.verify.correlation_id === run.id ? verified : null;
}

/** The AI CHANGES of the last executed approval when `run` names its simulation; else null. */
export function useRunChanges(run: AgentRun): AiChanges | null {
  const executed = useImpactStore((state) => state.executed);
  return executed && run.entries.some((entry) => entry.simulation_id === executed.simulation_id) ? executed.changes : null;
}
