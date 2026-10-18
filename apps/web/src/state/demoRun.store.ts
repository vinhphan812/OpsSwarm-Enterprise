import { create } from "zustand";
import i18n from "@/i18n";
import { errorMessage, notify } from "@/core/notify";
import type { DemoRun, DemoRunner } from "@/core/demo/demoRunner";
import { LENS, VIEW_MODE } from "@/enums/ui.enum";
import { usePanelStore } from "@/state/panel.store";
import { useUiStore } from "@/state/ui.store";

/** Where the Run AI Demo button stands. */
export const DEMO_RUN_STATUS = {
  Idle: "idle",
  /** Resetting the store and starting the run. */
  Starting: "starting",
  /** The run plays; the UI follows its stages while `following`. */
  Running: "running",
  Done: "done",
  Error: "error",
} as const;
export type DemoRunStatus = (typeof DEMO_RUN_STATUS)[keyof typeof DEMO_RUN_STATUS];

type DemoRunStore = {
  status: DemoRunStatus;
  /** The run's `correlation_id`, once started. */
  correlationId: string | null;
  /** Whether the UI follows the run's stages (view, lens, camera). Off after Stop following. */
  following: boolean;
  /** Why the last run failed, for the error and its Retry. */
  error: string | null;
  /** Resets the store and plays the flagship run with `runner`; nothing while one is starting or playing. */
  run: (runner: DemoRunner) => Promise<void>;
  /** Stops following the run: the view and the camera stay with the user; the run plays on. */
  stopFollowing: () => void;
};

/** The run in progress, to stop reading it when another one starts. */
let current: DemoRun | null = null;

/**
 * The Run AI Demo button's run. Starting one turns Follow agent on and opens the Operations
 * lens in Live; `useDemoDirector` then moves the view with the run's stages. A failure to
 * reach the controller, or a failed run, ends in `error`, with the store still usable.
 */
export const useDemoRunStore = create<DemoRunStore>()((set, get) => ({
  status: DEMO_RUN_STATUS.Idle,
  correlationId: null,
  following: false,
  error: null,
  run: async (runner) => {
    const { status } = get();
    if (status === DEMO_RUN_STATUS.Starting || status === DEMO_RUN_STATUS.Running) return;
    current?.stop();
    current = null;
    set({ status: DEMO_RUN_STATUS.Starting, correlationId: null, following: true, error: null });
    const ui = useUiStore.getState();
    ui.setFollowAgent(true);
    ui.setLens(LENS.Operations);
    ui.setViewMode(VIEW_MODE.Live);
    ui.showAllActivity();
    usePanelStore.getState().setOpen(true);
    try {
      const run = await runner.start();
      current = run;
      set({ status: DEMO_RUN_STATUS.Running, correlationId: run.correlationId });
      await run.done;
      if (current === run) set({ status: DEMO_RUN_STATUS.Done });
    } catch (error) {
      current?.stop();
      current = null;
      set({ status: DEMO_RUN_STATUS.Error, error: errorMessage(error) });
      notify.error(i18n.t("demo.failed"), error);
    }
  },
  stopFollowing: () => {
    set({ following: false });
    useUiStore.getState().setFollowAgent(false);
  },
}));

/** True while a run is starting or playing: the button is disabled. */
export function demoRunBusy(state: Pick<DemoRunStore, "status">): boolean {
  return state.status === DEMO_RUN_STATUS.Starting || state.status === DEMO_RUN_STATUS.Running;
}
