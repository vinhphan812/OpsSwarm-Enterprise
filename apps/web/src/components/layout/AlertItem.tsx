import { Chip } from "@heroui/react";
import { useTranslation } from "react-i18next";
import { alertCategory, alertStep, alertTarget } from "@/core/anomaly/alerts";
import { format } from "@/core/utils/format";
import { ALERT_CATEGORY, ALERT_STEPS } from "@/enums/anomaly.enum";
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

type AlertItemProps = {
  anomaly: Anomaly;
  activity: ActivityEntry[];
  inTwin: ReadonlySet<string>;
  /** Called after the alert is picked, such as to close the dialog it is in. */
  onPicked?: () => void;
};

/**
 * One alert or opportunity: kind, severity, the detector's title and description, where it
 * is, and how far its agent run has got. Picking it selects its product, or its shelf when
 * it has none, flies the camera there, and narrows the timeline to its run.
 */
export function AlertItem({ anomaly, activity, inTwin, onPicked }: AlertItemProps) {
  const { t } = useTranslation();
  const selectedId = useUiStore((state) => state.selectedEntityId);
  const selectedType = useUiStore((state) => state.selectedEntityType);
  const focusedCorrelationId = useUiStore((state) => state.focusedCorrelationId);
  const focusAlert = useUiStore((state) => state.focusAlert);

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
      onClick={() => {
        if (!target) return;
        focusAlert(correlationId, target.entityId, target.entityType);
        onPicked?.();
      }}
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
        <time dateTime={anomaly.detected_at}>{t("anomaly.detected", { time: format.hour(anomaly.detected_at) })}</time>
      </span>
      {target ? (
        <span className="alert-lifecycle">
          <span className="alert-steps" aria-hidden="true">
            {ALERT_STEPS.map((each, index) => (
              <span key={each} className="alert-step" data-done={index <= stepIndex} />
            ))}
          </span>
          <span className="alert-step-label">{t("alerts.step", { step: t(`alerts.steps.${step}`) })}</span>
        </span>
      ) : (
        <span className="alert-missing">{t("alerts.notInTwin")}</span>
      )}
    </button>
  );
}
