import { useTranslation } from "react-i18next";
import { PlayIcon, RetryIcon } from "@/components/icons";
import type { DemoRunner } from "@/core/demo/demoRunner";
import { DEMO_RUN_STATUS, demoRunBusy, useDemoRunStore } from "@/state/demoRun.store";

/**
 * ▶ Run AI Demo, the one place to start: resets the store and plays the flagship run, which
 * the UI then follows stage by stage (`useDemoDirector`). Disabled while a run starts or
 * plays, with Stop following to keep the view; a failure shows its reason and Retry. Says
 * whether it plays a replay of demo fixtures or the real flagship run of apps/api. Renders
 * nothing without a `runner` (the dev twins other than `?twin=demo`).
 */
export function RunDemoButton({ runner }: { runner: DemoRunner | null }) {
  const { t } = useTranslation();
  const status = useDemoRunStore((state) => state.status);
  const following = useDemoRunStore((state) => state.following);
  const error = useDemoRunStore((state) => state.error);
  const run = useDemoRunStore((state) => state.run);
  const stopFollowing = useDemoRunStore((state) => state.stopFollowing);
  if (!runner) return null;
  const busy = demoRunBusy({ status });

  const label =
    status === DEMO_RUN_STATUS.Starting
      ? t("demo.starting")
      : status === DEMO_RUN_STATUS.Running
        ? t("demo.running")
        : status === DEMO_RUN_STATUS.Done
          ? t("demo.again")
          : t("demo.run");

  return (
    <div className="run-demo" data-status={status}>
      <button
        type="button"
        className="run-demo-btn"
        disabled={busy}
        aria-busy={busy}
        title={t("demo.hint")}
        onClick={() => void run(runner)}
      >
        <PlayIcon className="h-3.5 w-3.5 shrink-0" />
        {label}
      </button>
      <span className="run-demo-source" data-source={runner.source}>
        {t(`demo.source.${runner.source}`)}
      </span>
      {status === DEMO_RUN_STATUS.Running && following ? (
        <button type="button" className="run-demo-stop" onClick={stopFollowing}>
          {t("demo.stopFollowing")}
        </button>
      ) : null}
      {status === DEMO_RUN_STATUS.Error ? (
        <div className="run-demo-error" role="alert">
          <span>{t("demo.error", { error })}</span>
          <button type="button" onClick={() => void run(runner)}>
            <RetryIcon className="h-3.5 w-3.5 shrink-0" />
            {t("demo.retry")}
          </button>
        </div>
      ) : null}
    </div>
  );
}
