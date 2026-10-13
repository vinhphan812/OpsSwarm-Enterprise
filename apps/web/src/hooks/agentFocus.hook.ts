import { useEffect } from "react";
import { agentFocusOf, agentFocusWait, type AgentFocus } from "@/core/agent/agentFocus";
import { useRunStore } from "@/state/run.store";
import { useUiStore } from "@/state/ui.store";

/**
 * Follows the agent: a new activity entry at a focusable stage (INVESTIGATE, ACT, VERIFY)
 * selects its product or fixture and flies the camera there, captioned with the entry's
 * summary (`focusEntity`). Nothing moves while Follow agent is off. While the user drags the
 * camera, or has used it in the last `AGENT_FOCUS_IDLE_MS`, the focus waits; only the
 * latest one is kept. The controls are never locked.
 */
export function useAgentFocus() {
  useEffect(() => {
    let pending: AgentFocus | null = null;
    let timer: ReturnType<typeof setTimeout> | undefined;

    const focusWhenIdle = () => {
      timer = undefined;
      const ui = useUiStore.getState();
      if (!pending || !ui.followAgent) {
        pending = null;
        return;
      }
      const wait = agentFocusWait(ui, Date.now());
      if (wait > 0) {
        timer = setTimeout(focusWhenIdle, wait);
        return;
      }
      ui.focusEntity(pending.entityId, pending.entityType, pending.reason);
      pending = null;
    };

    const unsubscribe = useRunStore.subscribe((state, previous) => {
      if (state.activity.length <= previous.activity.length) return;
      const focus = agentFocusOf(state.activity[state.activity.length - 1]);
      if (!focus || !useUiStore.getState().followAgent) return;
      pending = focus;
      clearTimeout(timer);
      focusWhenIdle();
    });
    return () => {
      unsubscribe();
      clearTimeout(timer);
    };
  }, []);
}
