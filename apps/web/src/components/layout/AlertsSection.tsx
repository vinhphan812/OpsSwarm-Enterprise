import { Chip } from "@heroui/react";
import { useMemo } from "react";
import { useTranslation } from "react-i18next";
import { alertCategory, alertStep, alertTarget, sortAlerts } from "@/core/anomaly/alerts";
import { format } from "@/core/utils/format";
import { ALERT_CATEGORY, ALERT_STEPS } from "@/enums/anomaly.enum";
import { useShownSimulation } from "@/hooks/activeTwin.hook";
import { useAnomalyStore } from "@/state/anomaly.store";
import { useRunStore } from "@/state/run.store";
import { useTwinStore } from "@/state/twin.store";
import { useUiStore } from "@/state/ui.store";
import type { ActivityEntry } from "@/types/agent.type";
import type { Anomaly } from "@/types/anomaly.type";

const CATEGORY_COLOR = {
  [ALERT_CATEGORY.Alert]: "danger",
  [ALERT_CATEGORY.Opportunity]: "success",
} as const;

/** Where an anomaly is: its product and shelf, its shelf alone, or the whole store. */
function AlertWhere({ anomaly }: { anomaly: Anomaly }) {
  const { t } = useTranslation();
  if (anomaly.sku && anomaly.shelf_id) return <span>{t("alerts.where", { sku: anomaly.sku, shelf: anomaly.shelf_id })}</span>;
  if (anomaly.sku) return <span>{anomaly.sku}</span>;
  if (anomaly.shelf_id) return <span>{t("alerts.whereShelf", { shelf: anomaly.shelf_id })}</span>;
  return <span>{t("alerts.whereStore")}</span>;
}

/**
 * Open alerts and opportunities, worst first, each with how far its agent run has got.
 * They appear as soon as the anomaly store has them, with no prompt. Title, description
 * and severity are the detector's (`GET /anomalies`). Picking one selects its product, or
 * its shelf when it has none, flies the camera there, and narrows the timeline to its run.
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

/** The alerts themselves, with the failed-read notice and the empty state. */
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
  const selectedId = useUiStore((state) => state.selectedEntityId);
  const selectedType = useUiStore((state) => state.selectedEntityType);
  const focusedCorrelationId = useUiStore((state) => state.focusedCorrelationId);
  const focusAlert = useUiStore((state) => state.focusAlert);

  return (
    <>
      {readError ? (
        <p className="alerts-error" role="status">
          {t(alerts.length ? "alerts.readFailedKept" : "alerts.readFailed", { error: readError })}
        </p>
      ) : null}
      {alerts.length ? (
        <ul className="alerts-list" aria-label={t("alerts.list")}>
          {alerts.map((anomaly) => {
            const category = alertCategory(anomaly);
            const step = alertStep(anomaly, activity);
            const stepIndex = ALERT_STEPS.indexOf(step);
            const target = alertTarget(anomaly, inTwin);
            const correlationId = anomaly.correlation_id ?? null;
            const pressed =
              target !== null &&
              selectedId === target.entityId &&
              selectedType === target.entityType &&
              focusedCorrelationId === correlationId;
            return (
              <li key={anomaly.anomaly_id}>
                <button
                  type="button"
                  className="alert-item"
                  data-severity={anomaly.severity}
                  data-category={category}
                  disabled={!target}
                  aria-pressed={pressed}
                  aria-label={t("alerts.select", {
                    category: t(`alerts.category.${category}`),
                    title: anomaly.title,
                  })}
                  onClick={() => target && focusAlert(correlationId, target.entityId, target.entityType)}
                >
                  <span className="alert-head">
                    <Chip size="sm" variant="flat" color={CATEGORY_COLOR[category]}>
                      {t(`alerts.category.${category}`)}
                    </Chip>
                    <span className="alert-type">{t(`anomaly.type.${anomaly.anomaly_type}`)}</span>
                    <span className="alert-severity">{t(`anomaly.severity.${anomaly.severity}`)}</span>
                  </span>
                  <span className="alert-title">{anomaly.title}</span>
                  <span className="alert-description">{anomaly.description}</span>
                  <span className="alert-meta">
                    <AlertWhere anomaly={anomaly} />
                    <time dateTime={anomaly.detected_at}>
                      {t("anomaly.detected", { time: format.hour(anomaly.detected_at) })}
                    </time>
                  </span>
                  {target ? (
                    <span className="alert-lifecycle">
                      <span className="alert-steps" aria-hidden="true">
                        {ALERT_STEPS.map((each, index) => (
                          <span key={each} className="alert-step" data-done={index <= stepIndex} />
                        ))}
                      </span>
                      <span className="alert-step-label">
                        {t("alerts.step", { step: t(`alerts.steps.${step}`) })}
                      </span>
                    </span>
                  ) : (
                    <span className="alert-missing">{t("alerts.notInTwin")}</span>
                  )}
                </button>
              </li>
            );
          })}
        </ul>
      ) : readError ? null : (
        <p className="alerts-empty">{t("alerts.empty")}</p>
      )}
    </>
  );
}
