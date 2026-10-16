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
