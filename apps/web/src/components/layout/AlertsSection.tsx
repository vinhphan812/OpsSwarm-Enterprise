import { useMemo, useState } from "react";
import { useTranslation } from "react-i18next";
import { ALERTS_SHOWN } from "@/constants/app.constant";
import { sortAlerts } from "@/core/anomaly/alerts";
import { useShownSimulation } from "@/hooks/activeTwin.hook";
import { useAnomalyStore } from "@/state/anomaly.store";
import { useRunStore } from "@/state/run.store";
import { useTwinStore } from "@/state/twin.store";
import type { ActivityEntry } from "@/types/agent.type";
import type { Anomaly } from "@/types/anomaly.type";
import { AlertItem } from "./AlertItem";
import { AlertsDialog } from "./AlertsDialog";

/**
 * Open alerts and opportunities, worst first, each with how far its agent run has got.
 * They appear as soon as the anomaly store has them, with no prompt. Title, description
 * and severity are the detector's (`GET /anomalies`); see `AlertItem` for what picking one does.
 * Only the worst few show in the panel; "Show all" opens the rest in a dialog, so the
 * timeline below stays in reach without a second scroll box inside the panel.
 * When a read of the anomalies fails it says so and keeps the last list, which may be out of date.
 * Anomalies describe Live, so the Simulation view lists none and says so.
 */
export function AlertsSection() {
  const { t } = useTranslation();
  const anomalies = useAnomalyStore((state) => state.anomalies);
  const readError = useAnomalyStore((state) => state.readError);
  const activity = useRunStore((state) => state.activity);
  const live = useTwinStore((state) => state.live);
  const simulation = useShownSimulation();
  const alerts = useMemo(() => sortAlerts(anomalies), [anomalies]);
  const inTwin = useMemo(() => new Set(live?.products.map((product) => product.sku)), [live]);

  return (
    <section className="activity-section alerts-section">
      <div className="activity-section-head">
        <h2 className="activity-section-title">
          {t("alerts.section")}
          <span className="activity-count">{alerts.length}</span>
        </h2>
      </div>
      {simulation ? (
        <p className="alerts-empty">{t("alerts.simulation")}</p>
      ) : (
        <AlertList alerts={alerts} readError={readError} activity={activity} inTwin={inTwin} />
      )}
    </section>
  );
}

/** The worst few alerts, "Show all" for the rest in a dialog, the failed-read notice and the empty state. */
function AlertList({
  alerts,
  readError,
  activity,
  inTwin,
}: {
  alerts: Anomaly[];
  readError: string | null;
  activity: ActivityEntry[];
  inTwin: ReadonlySet<string>;
}) {
  const { t } = useTranslation();
  const [dialogOpen, setDialogOpen] = useState(false);

  return (
    <>
      {readError ? (
        <p className="alerts-error" role="status">
          {t(alerts.length ? "alerts.readFailedKept" : "alerts.readFailed", { error: readError })}
        </p>
      ) : null}
      {alerts.length ? (
        <ul className="alerts-list" aria-label={t("alerts.list")}>
          {alerts.slice(0, ALERTS_SHOWN).map((anomaly) => (
            <li key={anomaly.anomaly_id}>
              <AlertItem anomaly={anomaly} activity={activity} inTwin={inTwin} />
            </li>
          ))}
        </ul>
      ) : null}
      {alerts.length > ALERTS_SHOWN ? (
        <button type="button" className="alerts-more" onClick={() => setDialogOpen(true)}>
          {t("alerts.showAllAlerts", { count: alerts.length })}
        </button>
      ) : null}
      {alerts.length || readError ? null : <p className="alerts-empty">{t("alerts.empty")}</p>}
      <AlertsDialog
        isOpen={dialogOpen}
        onClose={() => setDialogOpen(false)}
        alerts={alerts}
        activity={activity}
        inTwin={inTwin}
      />
    </>
  );
}
