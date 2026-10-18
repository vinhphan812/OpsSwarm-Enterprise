import { useTranslation } from "react-i18next";
import { useFlagshipStore } from "@/state/flagship.store";

/**
 * Renders the current `GET /flagship/status` snapshot at the top of the
 * Agent Activity panel. Shows the latest phase, DCG verdict, replan
 * status, verification, and the 8-stage timeline so the operator can see
 * exactly what the flagship chain did without leaving the page.
 *
 * Nothing is rendered before the first read; the polling hook clears
 * `status` on phase `IDLE` (or never sets it), so the panel goes back to
 * hidden once a new run starts.
 */
export function FlagshipStatusSection() {
  const { t } = useTranslation();
  const status = useFlagshipStore((state) => state.status);
  const error = useFlagshipStore((state) => state.error);
  if (!status) return null;
  // Hide the section once the controller is back at IDLE with no run.
  if (status.phase === "IDLE" && !status.run_id) return null;

  const verdictClass = verdictToClass(status.guard_verdict ?? null);

  return (
    <section className="activity-section flagship-status" data-testid="flagship-status">
      <div className="activity-section-head">
        <h2 className="activity-section-title">{t("flagship.section")}</h2>
        <span className={`flagship-phase phase-${status.phase.toLowerCase()}`}>{status.phase}</span>
      </div>

      {error ? (
        <p className="flagship-error" role="alert">
          {t("flagship.pollError", { error })}
        </p>
      ) : null}

      <div className="flagship-row">
        <span className="flagship-label">{t("flagship.runId")}</span>
        <code className="flagship-value">{status.run_id ?? "—"}</code>
      </div>
      <div className="flagship-row">
        <span className="flagship-label">{t("flagship.correlationId")}</span>
        <code className="flagship-value">{status.correlation_id ?? "—"}</code>
      </div>
      <div className="flagship-row">
        <span className="flagship-label">{t("flagship.contextVersion")}</span>
        <code className="flagship-value">{status.context_version ?? "—"}</code>
      </div>

      <div className={`flagship-verdict verdict-${verdictClass}`} data-testid="flagship-verdict">
        <span className="flagship-label">{t("flagship.guardVerdict")}</span>
        <span className="flagship-value-big">{status.guard_verdict ?? "—"}</span>
        <span className="flagship-reason">{status.guard_reason_code ?? ""}</span>
      </div>

      <div className="flagship-row">
        <span className="flagship-label">{t("flagship.committedDecision")}</span>
        <code className="flagship-value">{status.committed_decision_id ?? "—"}</code>
      </div>
      <div className="flagship-row">
        <span className="flagship-label">{t("flagship.replan")}</span>
        <span className="flagship-value">
          {status.replan_refresh_count ?? 0} refresh · reason {status.replan_reason_code ?? "—"}
        </span>
      </div>
      <div className="flagship-row">
        <span className="flagship-label">{t("flagship.verification")}</span>
        <span className="flagship-value">
          {status.verification_status ?? "—"} · reason {status.verification_reason_code ?? "—"}
        </span>
      </div>

      {status.timeline?.length ? (
        <details className="flagship-timeline" open>
          <summary>{t("flagship.timeline")} ({status.timeline.length})</summary>
          <ol className="flagship-timeline-list">
            {status.timeline.map((step, index) => (
              <li key={`${step.stage}-${index}`} className={`timeline-stage stage-${step.stage}`}>
                <span className="timeline-index">{index + 1}.</span>
                <span className="timeline-stage-name">{step.stage}</span>
                {step.detail ? <span className="timeline-detail"> — {step.detail}</span> : null}
              </li>
            ))}
          </ol>
        </details>
      ) : null}

      {status.error ? (
        <p className="flagship-error-detail" role="alert">
          {t("flagship.runError", { error: status.error })}
        </p>
      ) : null}
    </section>
  );
}

function verdictToClass(verdict: string | null): string {
  if (!verdict) return "unknown";
  const v = verdict.toLowerCase();
  if (v === "allow") return "allow";
  if (v === "refresh_required") return "refresh";
  if (v === "deny") return "deny";
  if (v === "human_review") return "human";
  return "unknown";
}