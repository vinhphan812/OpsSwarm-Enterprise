import { Button } from "@heroui/react";
import { useTranslation } from "react-i18next";
import { useErrorLogStore } from "@/state/errorLog.store";

/**
 * Error log section showing persistent errors from API calls, polling, and other operations.
 * Appears in the Operations panel below alerts when there are errors to show.
 * Provides clear and dismiss functionality.
 */
export function ErrorLogSection() {
  const { t } = useTranslation();
  const entries = useErrorLogStore((state) => state.entries);
  const clear = useErrorLogStore((state) => state.clear);
  const remove = useErrorLogStore((state) => state.remove);

  if (!entries.length) {
    return null;
  }

  return (
    <section className="activity-section error-log-section">
      <div className="activity-section-head">
        <h2 className="activity-section-title">
          {t("errorLog.title")}
          <span className="activity-count error-count">{entries.length}</span>
        </h2>
        <Button
          size="sm"
          variant="light"
          onPress={clear}
          className="cursor-pointer text-xs text-ink-muted data-[hover=true]:text-danger"
        >
          {t("errorLog.clear")}
        </Button>
      </div>

      <ul className="error-log-list" aria-label={t("errorLog.title")}>
        {entries.map((entry) => (
          <li key={entry.id} className="error-log-item">
            <div className="error-log-header">
              <span className="error-log-time">{new Date(entry.timestamp).toLocaleTimeString()}</span>
              <span className="error-log-source">{entry.source}</span>
              <button
                type="button"
                className="error-log-dismiss"
                onClick={() => remove(entry.id)}
                aria-label={t("errorLog.dismiss")}
              >
                ×
              </button>
            </div>
            <p className="error-log-message">{entry.message}</p>
            {entry.details ? <p className="error-log-details">{entry.details}</p> : null}
            {entry.recoverable ? (
              <span className="error-log-recoverable">{t("errorLog.recoverable")}</span>
            ) : null}
          </li>
        ))}
      </ul>
    </section>
  );
}
