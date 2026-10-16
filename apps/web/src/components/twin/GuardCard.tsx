import { useTranslation } from "react-i18next";
import { CheckIcon, CloseIcon, MinusIcon, ShieldIcon } from "@/components/icons";
import { GATE_STATE, gateRows, type GateState } from "@/core/twin/guardChecks";
import { GUARD_VERDICT, SIMULATION_STATUS } from "@/enums/simulation.enum";
import type { GuardReview } from "@/state/guard.store";

const GATE_ICON = {
  [GATE_STATE.Passed]: CheckIcon,
  [GATE_STATE.Failed]: CloseIcon,
  [GATE_STATE.NotRun]: MinusIcon,
} satisfies Record<GateState, unknown>;

/**
 * The Decision Context Guard's answer to one approval: its verdict, why, what happened to
 * Live, and the gates it ran. Everything shown is what the review returned; a guard that
 * sent no checks shows none.
 */
export function GuardCard({ review }: { review: GuardReview }) {
  const { t } = useTranslation();
  const { result, base_context_version: base } = review;
  const verdict = result.verdict ?? GUARD_VERDICT.HumanReview;
  const guard = result.guard;
  const code = result.reason_code ?? guard?.reason_code ?? null;
  const reason = (value: string) => t(`guard.reason.${value}`, { defaultValue: value });
  const rows = guard ? gateRows(guard) : [];
  const committed = result.status === SIMULATION_STATUS.Committed;
  const liveMoved =
    verdict === GUARD_VERDICT.RefreshRequired && result.live_context_version && result.live_context_version !== base;

  return (
    <section className="guard-card" data-verdict={verdict} aria-label={t("guard.label", { id: result.simulation_id })}>
      <header className="guard-card-head">
        <span className="guard-card-title">
          <ShieldIcon className="h-4 w-4 shrink-0" />
          {t("guard.title")}
        </span>
        <span className="guard-card-verdict">{t(`guard.verdict.${verdict}`)}</span>
      </header>
      <span className="guard-card-meta">
        {t("guard.checkedAgainst", { id: result.simulation_id, version: guard?.context_version ?? base })}
      </span>
      {code ? <p className="guard-card-reason">{reason(code)}</p> : null}
      {liveMoved ? (
        <p className="guard-card-versions">
          {t("guard.liveMoved", { base, live: result.live_context_version })}
          <span>{t("guard.regenerate")}</span>
        </p>
      ) : null}
      <p className="guard-card-outcome">
        {committed && result.live_context_version
          ? t("guard.committed", { version: result.live_context_version })
          : t("guard.notCommitted")}
      </p>
      {rows.length ? (
        <ul className="guard-card-gates" aria-label={t("guard.gates")}>
          {rows.map((row) => {
            const Icon = GATE_ICON[row.state];
            return (
              <li key={row.gate} data-state={row.state}>
                <Icon className="guard-gate-icon" />
                <span className="guard-gate-name">{t(`guard.gate.${row.gate}`, { defaultValue: row.gate })}</span>
                <span className="guard-gate-state">{t(`guard.check.${row.state}`)}</span>
                {row.detail ? <span className="guard-gate-detail">{row.detail}</span> : null}
              </li>
            );
          })}
        </ul>
      ) : (
        <p className="guard-card-meta">{t("guard.noChecks")}</p>
      )}
    </section>
  );
}
