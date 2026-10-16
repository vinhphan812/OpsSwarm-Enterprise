import { STAGE_STATUS, type StageStatus } from "@/enums/agent.enum";
import type { ActivityEntry, ControlStage } from "@/types/agent.type";

/** The control loop, in order. */
export const CONTROL_STAGES: readonly ControlStage[] = [
  "OBSERVE",
  "DETECT",
  "INVESTIGATE",
  "PLAN",
  "SIMULATE",
  "GUARD",
  "ACT",
  "VERIFY",
];

/** One stage of a run: where it stands, and the run's entries for it, oldest first. */
export type RunStage = { stage: ControlStage; status: StageStatus; entries: ActivityEntry[] };

/** The entries sharing one `correlation_id`: one pass of the agent through the control loop. */
export type AgentRun = {
  id: string;
  /** Oldest first. */
  entries: ActivityEntry[];
  /** Every stage of `CONTROL_STAGES`, in order. */
  stages: RunStage[];
  /** The first SKU the run names, or null. */
  sku: string | null;
};

/** The timeline grouped into runs, newest first, and the entries that belong to no run. */
export type GroupedActivity = { runs: AgentRun[]; loose: ActivityEntry[] };

/**
 * Groups the timeline (oldest first, as `run.store` holds it) by `correlation_id`. A stage
 * with an entry is done; the stage of the latest entry is active until the run reaches
 * VERIFY; any other stage stays pending, however far the run got. Runs are ordered by
 * their latest entry, newest first.
 */
export function groupRuns(activity: readonly ActivityEntry[]): GroupedActivity {
  const byId = new Map<string, { entries: ActivityEntry[]; last: number }>();
  const loose: ActivityEntry[] = [];
  activity.forEach((entry, index) => {
    if (!entry.correlation_id) {
      loose.push(entry);
      return;
    }
    const group = byId.get(entry.correlation_id);
    if (group) {
      group.entries.push(entry);
      group.last = index;
    } else {
      byId.set(entry.correlation_id, { entries: [entry], last: index });
    }
  });
  const runs = [...byId.entries()]
    .sort(([, a], [, b]) => b.last - a.last)
    .map(([id, { entries }]) => toRun(id, entries));
  return { runs, loose };
}

function toRun(id: string, entries: ActivityEntry[]): AgentRun {
  const latest = entries[entries.length - 1].stage;
  const active = latest === "VERIFY" ? null : latest;
  const stages = CONTROL_STAGES.map((stage): RunStage => {
    const own = entries.filter((entry) => entry.stage === stage);
    const status = stage === active ? STAGE_STATUS.Active : own.length ? STAGE_STATUS.Done : STAGE_STATUS.Pending;
    return { stage, status, entries: own };
  });
  return { id, entries, stages, sku: entries.find((entry) => entry.sku)?.sku ?? null };
}
