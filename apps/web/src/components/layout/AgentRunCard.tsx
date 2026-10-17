import { motion } from "framer-motion";
import { useTranslation } from "react-i18next";
import { AiChangesList } from "@/components/twin/AiChangesList";
import { AiImpactCard } from "@/components/twin/AiImpactCard";
import type { AgentRun } from "@/core/agent/agentRuns";
import { STAGE_STATUS } from "@/enums/agent.enum";
import { useRunChanges, useRunImpact } from "@/hooks/aiImpact.hook";
import { clock, SkuChip } from "./ActivityLog";

/**
 * One agent run as a card: the eight stages of the control loop as a vertical stepper,
 * each with its own summaries. A stage the run has no entry for stays pending. The run of an
 * executed approval also lists its AI CHANGES under ACT, and its projected impact under
 * VERIFY once it gets there.
 */
export function AgentRunCard({ run }: { run: AgentRun }) {
  const { t } = useTranslation();
  const first = run.entries[0];
  const active = run.stages.find((stage) => stage.status === STAGE_STATUS.Active);
  const label = run.sku ? t("activity.run.titleSku", { sku: run.sku }) : t("activity.run.title");
  const changes = useRunChanges(run);
  const impact = useRunImpact(run);

  return (
    <motion.li
      layout
      className="run-card"
      data-testid="agent-run"
      data-run={run.id}
      initial={{ opacity: 0, y: 8 }}
      animate={{ opacity: 1, y: 0 }}
      exit={{ opacity: 0 }}
      transition={{ duration: 0.22, ease: "easeOut" }}
    >
      <header className="run-card-head">
        <h3 className="run-card-title">{label}</h3>
        <time className="run-card-time" dateTime={first.ts}>
          {clock(first.ts)}
        </time>
        <span className="run-card-state" data-active={active ? "true" : undefined}>
          {active ? t("activity.run.at", { stage: active.stage }) : t("activity.run.complete")}
        </span>
      </header>
      <ol className="run-steps" aria-label={t("activity.run.steps", { run: label })}>
        {run.stages.map(({ stage, status, entries }) => (
          <li
            key={stage}
            className="run-step"
            data-status={status}
            aria-current={status === STAGE_STATUS.Active ? "step" : undefined}
          >
            <span className="run-step-dot" aria-hidden="true" />
            <div className="run-step-body">
              <span className="run-step-name">
                {stage}
                <span className="sr-only">{t(`activity.stageStatus.${status}`)}</span>
              </span>
              {entries.map((entry) => (
                <div key={entry.id} className="run-step-entry">
                  <p className="activity-summary">{entry.summary}</p>
                  <div className="activity-meta">
                    <time dateTime={entry.ts}>{clock(entry.ts)}</time>
                    {entry.sku ? <SkuChip sku={entry.sku} /> : null}
                  </div>
                </div>
              ))}
              {stage === "ACT" ? <AiChangesList changes={changes} /> : null}
              {stage === "VERIFY" && impact ? <AiImpactCard impact={impact.impact} verify={impact.verify} /> : null}
            </div>
          </li>
        ))}
      </ol>
    </motion.li>
  );
}
