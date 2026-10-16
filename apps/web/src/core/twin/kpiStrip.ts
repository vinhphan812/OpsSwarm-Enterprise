import { REVENUE_TODAY_STALE_MS } from "@/constants/app.constant";
import { ANOMALY_TYPE } from "@/enums/anomaly.enum";
import { KPI_NAME } from "@/enums/simulation.enum";
import type { Anomaly } from "@/types/anomaly.type";
import type { RevenueSummary } from "@/types/revenue.type";
import type { Candidate } from "@/types/simulation.type";
import type { StoreResponse } from "@/types/twin.type";
import { compareCandidates } from "./candidateComparison";

/**
 * Where a tile of the KPI strip stands: a value from its source, or why there is none.
 * A tile never shows a value its source did not serve, and never a 0 for a missing one.
 */
export type KpiTileValue<T> = { value: T; reason?: undefined } | { value: null; reason: KpiMissing };

/** Why a tile shows "—". */
export const KPI_MISSING = {
  /** The source has not answered, or did not answer the last read. */
  NotServed: "notServed",
  /** The source has not answered for `REVENUE_TODAY_STALE_MS`, so its last value is no longer shown. */
  Stale: "stale",
  /** The source answered with nothing to count. */
  Empty: "empty",
  /** No open simulation, so the KPI evaluator has nothing to score. */
  NoSimulation: "noSimulation",
  /** The open simulation's candidates carry no baseline or no scored proposal. */
  NotScored: "notScored",
} as const;
export type KpiMissing = (typeof KPI_MISSING)[keyof typeof KPI_MISSING];

const missing = (reason: KpiMissing) => ({ value: null, reason }) as const;

/**
 * What a tile counts: `recorded` (served by a store route), `live` (the Live Twin or its
 * feeds), or `projected` (the KPI evaluator on a simulation, never measured in the store).
 * A tile has one basis, so Simulation numbers never mix into a Live one.
 */
export const KPI_BASIS = {
  Recorded: "recorded",
  Live: "live",
  Projected: "projected",
} as const;
export type KpiBasis = (typeof KPI_BASIS)[keyof typeof KPI_BASIS];

/** A read with the time it landed, in ms since the epoch. */
export type TimedRead<T> = { value: T; readAt: number };

/**
 * Today's revenue as `GET /revenue?period=today` served it: missing until it has, and again
 * once the last good read is older than `REVENUE_TODAY_STALE_MS` at `now`.
 */
export function revenueToday(read: TimedRead<RevenueSummary> | null, now: number): KpiTileValue<number> {
  if (!read) return missing(KPI_MISSING.NotServed);
  if (now - read.readAt > REVENUE_TODAY_STALE_MS) return missing(KPI_MISSING.Stale);
  return { value: read.value.revenue };
}

/** Products of the Live Twin (`GET /store`) with stock on the shelf, out of every served product. */
export type Availability = { onShelf: number; total: number; share: number };

export function onShelfAvailability(live: StoreResponse | null): KpiTileValue<Availability> {
  if (!live) return missing(KPI_MISSING.NotServed);
  const total = live.products.length;
  if (!total) return missing(KPI_MISSING.Empty);
  const onShelf = live.products.filter((product) => product.shelf_quantity > 0).length;
  return { value: { onShelf, total, share: onShelf / total } };
}

/** Products with an open stockout in the anomaly feed (`GET /anomalies`); null until the feed is served. */
export function stockoutRisk(anomalies: readonly Anomaly[], served: boolean): KpiTileValue<number> {
  if (!served) return missing(KPI_MISSING.NotServed);
  const skus = new Set(
    anomalies.filter((anomaly) => anomaly.anomaly_type === ANOMALY_TYPE.Stockout).map((anomaly) => anomaly.sku ?? anomaly.anomaly_id),
  );
  return { value: skus.size };
}

/** The projected `business_score` move of one candidate over the baseline, as the KPI evaluator scored it. */
export type ProjectedImpact = { candidateId: string; delta: number; evaluatorVersion: string };

/**
 * The AI impact of the open simulation: the selected candidate's `business_score` against the
 * baseline's, or the top-scored candidate's while none is selected. A projection by the KPI
 * evaluator, never an observed result. TODO(#209): the accepted plan's impact once it is on main.
 */
export function projectedImpact(
  candidates: readonly Candidate[],
  hasSimulation: boolean,
  selectedId: string | null,
): KpiTileValue<ProjectedImpact> {
  if (!hasSimulation) return missing(KPI_MISSING.NoSimulation);
  const { proposals, rows, topScoreId } = compareCandidates([...candidates]);
  const candidateId = selectedId ?? topScoreId;
  const cell = candidateId ? rows.find((row) => row.name === KPI_NAME.BusinessScore)?.cells[candidateId] : undefined;
  const candidate = proposals.find((item) => item.candidate_id === candidateId);
  if (!candidateId || !candidate || !cell || cell.delta === null) return missing(KPI_MISSING.NotScored);
  return { value: { candidateId, delta: cell.delta, evaluatorVersion: candidate.evaluator_version } };
}
