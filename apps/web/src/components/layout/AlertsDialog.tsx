import { useMemo, useState } from "react";
import { useTranslation } from "react-i18next";
import { ListDialog } from "@/components/common/ListDialog";
import { Segmented } from "@/components/commerce/Segmented";
import { alertCategory } from "@/core/anomaly/alerts";
import { ALERT_CATEGORY, type AlertCategory } from "@/enums/anomaly.enum";
import type { ActivityEntry } from "@/types/agent.type";
import type { Anomaly } from "@/types/anomaly.type";
import { AlertItem } from "./AlertItem";

const ALL = "all";
type CategoryFilter = AlertCategory | typeof ALL;
const FILTERS: readonly CategoryFilter[] = [ALL, ALERT_CATEGORY.Alert, ALERT_CATEGORY.Opportunity];

/** Whether an alert's title, SKU, or shelf contains the query, ignoring case. */
function matches(anomaly: Anomaly, query: string) {
  const needle = query.trim().toLowerCase();
  if (!needle) return true;
  return [anomaly.title, anomaly.sku, anomaly.shelf_id].some((field) => field?.toLowerCase().includes(needle));
}

type AlertsDialogProps = {
  isOpen: boolean;
  onClose: () => void;
  /** Already sorted, worst first. */
  alerts: Anomaly[];
  activity: ActivityEntry[];
  inTwin: ReadonlySet<string>;
};

/**
 * Every open alert and opportunity, filtered by kind or a search.
 * Picking one does what it does in the panel, then closes the dialog so the 3D view shows it.
 */
export function AlertsDialog({ isOpen, onClose, alerts, activity, inTwin }: AlertsDialogProps) {
  const { t } = useTranslation();
  const [filter, setFilter] = useState<CategoryFilter>(ALL);
  const [query, setQuery] = useState("");

  const shown = useMemo(
    () => alerts.filter((anomaly) => (filter === ALL || alertCategory(anomaly) === filter) && matches(anomaly, query)),
    [alerts, filter, query],
  );
  const countOf = (value: CategoryFilter) =>
    value === ALL ? alerts.length : alerts.filter((anomaly) => alertCategory(anomaly) === value).length;

  return (
    <ListDialog
      isOpen={isOpen}
      onClose={onClose}
      title={t("alerts.dialog.title")}
      empty={t("alerts.dialog.empty")}
      isEmpty={shown.length === 0}
      toolbar={
        <>
          <Segmented
            variant="chips"
            label={t("alerts.dialog.filter")}
            layoutId="alert-category-filter"
            value={filter}
            onChange={setFilter}
            options={FILTERS.map((value) => ({
              value,
              label: value === ALL ? t("alerts.dialog.all") : t(`alerts.dialog.category.${value}`),
              badge: countOf(value),
            }))}
          />
          <input
            type="search"
            className="text-field dialog-search"
            aria-label={t("alerts.dialog.search")}
            placeholder={t("alerts.dialog.search")}
            value={query}
            onChange={(event) => setQuery(event.target.value)}
            autoComplete="off"
          />
        </>
      }
    >
      <ul className="alerts-list" aria-label={t("alerts.dialog.list")}>
        {shown.map((anomaly) => (
          <li key={anomaly.anomaly_id}>
            <AlertItem anomaly={anomaly} activity={activity} inTwin={inTwin} onPicked={onClose} />
          </li>
        ))}
      </ul>
    </ListDialog>
  );
}
