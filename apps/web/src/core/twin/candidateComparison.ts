import { BASELINE_CANDIDATE_ID, KPI_NAME, KPI_TREND, LOWER_IS_BETTER_KPIS, type KpiTrend } from "@/enums/simulation.enum";
import type { Candidate, CandidateKPI } from "@/types/simulation.type";

/** One candidate's value of a KPI, with how far it moved from the baseline's. */
export type KpiCell = {
  /** The KPI exactly as served. */
  kpi: CandidateKPI;
  /** `kpi.value` minus the baseline's, or null without a baseline value. */
  delta: number | null;
  trend: KpiTrend | null;
};

/** One KPI across the candidates. A candidate with no such KPI has no cell. */
export type KpiRow = {
  name: string;
  baseline: CandidateKPI | null;
  cells: Record<string, KpiCell | undefined>;
};

export type CandidateComparison = {
  /** The candidate with no actions, scored on the base state; null when none is served. */
  baseline: Candidate | null;
  /** The candidates that propose something, in served order. */
  proposals: Candidate[];
  /** Every KPI any candidate has, in the order first served. */
  rows: KpiRow[];
  /** The proposal with the single highest served `business_score`, or null (none scored, or a tie). */
  topScoreId: string | null;
};

/** Digits after the point of `value` as written, so a delta keeps the served precision. */
function decimals(value: number): number {
  const [, fraction = ""] = String(value).split(".");
  return fraction.length;
}

/**
 * `after - before`, rounded to the more precise of the two, so 0.27 - 0.11 is 0.16 and
 * not 0.16000000000000003. A display-only difference of two served values: the FE never
 * computes a KPI itself.
 */
export function kpiDelta(after: number, before: number): number {
  const places = Math.min(Math.max(decimals(after), decimals(before)), 10);
  const delta = Number((after - before).toFixed(places));
  return Object.is(delta, -0) ? 0 : delta;
}

/** Whether a move of `delta` in KPI `name` is for the better, for the worse, or none. */
export function kpiTrend(name: string, delta: number): KpiTrend {
  if (delta === 0) return KPI_TREND.Same;
  const up = delta > 0;
  return up !== LOWER_IS_BETTER_KPIS.includes(name) ? KPI_TREND.Better : KPI_TREND.Worse;
}

/** Lays out the candidates of a run for side-by-side comparison, keeping every value as served. */
export function compareCandidates(candidates: Candidate[]): CandidateComparison {
  const baseline = candidates.find((candidate) => candidate.candidate_id === BASELINE_CANDIDATE_ID) ?? null;
  const proposals = candidates.filter((candidate) => candidate !== baseline);

  const names: string[] = [];
  for (const candidate of [...(baseline ? [baseline] : []), ...proposals]) {
    for (const kpi of candidate.kpis) if (!names.includes(kpi.name)) names.push(kpi.name);
  }

  const rows = names.map((name): KpiRow => {
    const before = baseline?.kpis.find((kpi) => kpi.name === name) ?? null;
    const cells: KpiRow["cells"] = {};
    for (const candidate of proposals) {
      const kpi = candidate.kpis.find((item) => item.name === name);
      if (!kpi) continue;
      const delta = before ? kpiDelta(kpi.value, before.value) : null;
      cells[candidate.candidate_id] = { kpi, delta, trend: delta === null ? null : kpiTrend(name, delta) };
    }
    return { name, baseline: before, cells };
  });

  return { baseline, proposals, rows, topScoreId: topScore(rows, proposals) };
}

function topScore(rows: KpiRow[], proposals: Candidate[]): string | null {
  const row = rows.find((item) => item.name === KPI_NAME.BusinessScore);
  if (!row) return null;
  let top: string | null = null;
  let best = -Infinity;
  let tied = false;
  for (const { candidate_id } of proposals) {
    const value = row.cells[candidate_id]?.kpi.value;
    if (value === undefined) continue;
    if (value > best) [top, best, tied] = [candidate_id, value, false];
    else if (value === best) tied = true;
  }
  return tied ? null : top;
}
