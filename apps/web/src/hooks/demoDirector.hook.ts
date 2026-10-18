import { useEffect } from "react";
import { LENS, VIEW_MODE } from "@/enums/ui.enum";
import { DEMO_RUN_STATUS, useDemoRunStore } from "@/state/demoRun.store";
import { usePanelStore } from "@/state/panel.store";
import { useRunStore } from "@/state/run.store";
import { useTwinStore } from "@/state/twin.store";
import { useUiStore } from "@/state/ui.store";
import type { ActivityEntry, ControlStage } from "@/types/agent.type";

/** The agent stages in the order a run passes them. */
const STAGE_ORDER: readonly ControlStage[] = ["OBSERVE", "DETECT", "INVESTIGATE", "PLAN", "SIMULATE", "GUARD", "ACT", "VERIFY"];

/** Where the run ends up in the UI: Live, the Operations lens, the panel open. */
function settleOnLive() {
  const ui = useUiStore.getState();
  ui.setViewMode(VIEW_MODE.Live);
  ui.setLens(LENS.Operations);
  usePanelStore.getState().setOpen(true);
}

/** Whether the open simulation is the one `entry` names; any open one when it names none. */
function simulationOpenFor(entry: ActivityEntry): boolean {
  const open = useTwinStore.getState().simulation;
  return open !== null && (!entry.simulation_id || entry.simulation_id === open.simulation_id);
}

/**
 * Moves the UI with the stages of the Run AI Demo run, as its entries arrive: the
 * Simulation view at SIMULATE (once that simulation is open), Live again at ACT, and the
 * Operations lens at VERIFY. The camera follows through Follow agent (`useAgentFocus`).
 * Only an entry of the run moves anything, so the UI never runs ahead of the agent; after
 * Stop following nothing moves. A stage that arrives after a later one (a late SIMULATE
 * after ACT) moves nothing, and a run that ends without a VERIFY entry still ends on Live
 * and the Operations lens. TODO(#206, #209): show the guard card at GUARD and the AI
 * Impact card at VERIFY once they are on main.
 */
export function useDemoDirector() {
  useEffect(() => {
    /** SIMULATE arrived before its simulation was read: switch once it is open. */
    let awaitingSimulation: ActivityEntry | null = null;
    /** The furthest stage of the run the UI has followed, by `STAGE_ORDER`. */
    let reached = -1;

    const following = () => {
      const demo = useDemoRunStore.getState();
      return demo.status === DEMO_RUN_STATUS.Running && demo.following;
    };

    const onEntry = (entry: ActivityEntry) => {
      const rank = STAGE_ORDER.indexOf(entry.stage);
      if (rank < reached) return;
      reached = rank;
      const ui = useUiStore.getState();
      switch (entry.stage) {
        case "SIMULATE":
          awaitingSimulation = null;
          if (simulationOpenFor(entry)) ui.setViewMode(VIEW_MODE.Simulation);
          else awaitingSimulation = entry;
          return;
        case "ACT":
          awaitingSimulation = null;
          ui.setViewMode(VIEW_MODE.Live);
          return;
        case "VERIFY":
          awaitingSimulation = null;
          settleOnLive();
          return;
      }
    };

    const stopRun = useRunStore.subscribe((run, before) => {
      if (run.activity.length <= before.activity.length || !following()) return;
      const { correlationId } = useDemoRunStore.getState();
      for (const entry of run.activity.slice(before.activity.length)) {
        if (entry.correlation_id === correlationId) onEntry(entry);
      }
    });
    const stopTwin = useTwinStore.subscribe((twin, before) => {
      if (!awaitingSimulation || twin.simulation === before.simulation || !following()) return;
      if (simulationOpenFor(awaitingSimulation)) {
        awaitingSimulation = null;
        useUiStore.getState().setViewMode(VIEW_MODE.Simulation);
      }
    });
    const stopDemo = useDemoRunStore.subscribe((demo, before) => {
      if (demo.correlationId !== before.correlationId) reached = -1;
      if (!demo.following || demo.status !== DEMO_RUN_STATUS.Running) awaitingSimulation = null;
      if (demo.following && before.status === DEMO_RUN_STATUS.Running && demo.status === DEMO_RUN_STATUS.Done) settleOnLive();
    });
    return () => {
      stopRun();
      stopTwin();
      stopDemo();
    };
  }, []);
}
