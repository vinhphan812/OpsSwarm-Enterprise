import { Chip } from "@heroui/react";
import { useTranslation } from "react-i18next";
import { format } from "@/core/utils/format";
import { ANOMALY_SEVERITY } from "@/enums/anomaly.enum";
import type { Anomaly } from "@/types/anomaly.type";

const SEVERITY_COLOR = {
  [ANOMALY_SEVERITY.Low]: "default",
  [ANOMALY_SEVERITY.Medium]: "warning",
  [ANOMALY_SEVERITY.High]: "danger",
} as const;

/** A product's open anomalies: kind, severity, and since when. One read from an older twin state says so. */
export function AnomalyList({ anomalies, contextVersion }: { anomalies: Anomaly[]; contextVersion: string }) {
  const { t } = useTranslation();
  if (anomalies.length === 0) return null;
  return (
    <ul className="flex flex-col gap-1" aria-label={t("anomaly.list")}>
      {anomalies.map((anomaly) => (
        <li key={anomaly.anomaly_id} className="flex flex-wrap items-center gap-2">
          <Chip size="sm" variant="flat" color={SEVERITY_COLOR[anomaly.severity]}>
            {t(`anomaly.kind.${anomaly.kind}`)} · {t(`anomaly.severity.${anomaly.severity}`)}
          </Chip>
          <span className="text-default-500">{t("anomaly.detected", { time: format.hour(anomaly.detected_at) })}</span>
          {anomaly.context_version !== contextVersion ? (
            <span className="text-default-500">{t("anomaly.olderState")}</span>
          ) : null}
        </li>
      ))}
    </ul>
  );
}
