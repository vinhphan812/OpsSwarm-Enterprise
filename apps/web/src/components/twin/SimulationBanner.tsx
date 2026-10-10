import { useTranslation } from "react-i18next";
import { SimulationIcon } from "@/components/icons";
import { isNewerVersion } from "@/core/api/version";
import { useShownSimulation } from "@/hooks/activeTwin.hook";
import { useTwinStore } from "@/state/twin.store";

/**
 * While the Simulation view is on: a frame around the 3D view and a label naming the run,
 * the live state it started from, and that nothing in it has been executed. Says so when
 * Live has moved on since. Renders nothing in the Live view.
 */
export function SimulationBanner() {
  const { t } = useTranslation();
  const simulation = useShownSimulation();
  const liveVersion = useTwinStore((state) => state.live?.context_version ?? null);
  if (!simulation) return null;

  const behind = liveVersion !== null && isNewerVersion(liveVersion, simulation.base_context_version);
  return (
    <>
      <div className="simulation-frame" aria-hidden />
      <div className="simulation-banner" role="status" aria-label={t("simulation.label")}>
        <span className="simulation-banner-title">
          <SimulationIcon className="h-4 w-4 shrink-0" />
          {t("simulation.title")}
        </span>
        <span>{t("simulation.notExecuted")}</span>
        <span className="simulation-banner-meta">
          {t("simulation.run", { id: simulation.simulation_id, status: t(`simulation.status.${simulation.status}`) })}
          {" · "}
          {t("simulation.basedOn", { version: simulation.base_context_version })}
        </span>
        {behind ? <span className="simulation-banner-stale">{t("simulation.liveMoved", { version: liveVersion })}</span> : null}
      </div>
    </>
  );
}
