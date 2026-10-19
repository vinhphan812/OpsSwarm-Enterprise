import { LOCALE, STORE_TIME_ZONE } from "@/constants/i18n.constant";
import { REVENUE_GRAIN, REVENUE_PERIOD, type RevenueGrain, type RevenuePeriod } from "@/enums/commerce.enum";

/**
 * What `GET /revenue` is asked for one window of the Revenue lens: apps/api's `period` (the
 * bucket grain) and the window's ISO `start` and `end`. apps/api reads sales at `start <= t <= end`.
 */
export type RevenueQuery = { period: RevenueGrain; start: string; end: string };

/** Calendar days each window covers, today included. */
const WINDOW_DAYS: Record<RevenuePeriod, number> = {
  [REVENUE_PERIOD.Today]: 1,
  [REVENUE_PERIOD.Week]: 7,
  [REVENUE_PERIOD.Month]: 30,
};

type CivilDate = { year: number; month: number; day: number };

const partsFormat = new Map<string, Intl.DateTimeFormat>();

/** Wall-clock fields of `instant` in `timeZone`. */
function wallClock(instant: number, timeZone: string) {
  let format = partsFormat.get(timeZone);
  if (!format) {
    format = new Intl.DateTimeFormat("en-US", {
      timeZone,
      hourCycle: "h23",
      year: "numeric",
      month: "numeric",
      day: "numeric",
      hour: "numeric",
      minute: "numeric",
      second: "numeric",
    });
    partsFormat.set(timeZone, format);
  }
  const fields: Record<string, number> = {};
  for (const part of format.formatToParts(instant)) {
    if (part.type !== "literal") fields[part.type] = Number(part.value);
  }
  return fields as { year: number; month: number; day: number; hour: number; minute: number; second: number };
}

/** How far `timeZone`'s wall clock is ahead of UTC at `instant`, in ms. */
function offsetAt(instant: number, timeZone: string): number {
  const wall = wallClock(instant, timeZone);
  const asUtc = Date.UTC(wall.year, wall.month - 1, wall.day, wall.hour, wall.minute, wall.second);
  return asUtc - Math.floor(instant / 1000) * 1000;
}

/**
 * The instant `date` begins in `timeZone`: its first moment, which is 00:00 on most days and
 * the first wall time after a daylight-saving gap when midnight is skipped.
 */
export function startOfDay(date: CivilDate, timeZone: string): number {
  const midnightUtc = Date.UTC(date.year, date.month - 1, date.day);
  // Two passes settle the offset when the day starts on one side of a daylight-saving change.
  let instant = midnightUtc - offsetAt(midnightUtc, timeZone);
  instant = midnightUtc - offsetAt(instant, timeZone);
  const wall = wallClock(instant, timeZone);
  // Midnight fell in a gap: the clock jumped past it, so the day starts at the jump.
  if (wall.day !== date.day) instant += 3_600_000 - ((wall.minute * 60 + wall.second) * 1000 + (instant % 1000));
  return instant;
}

/** The calendar date `days` before the date of `instant` in `timeZone`. */
function dateBefore(instant: number, days: number, timeZone: string): CivilDate {
  const wall = wallClock(instant, timeZone);
  const shifted = new Date(Date.UTC(wall.year, wall.month - 1, wall.day - days));
  return { year: shifted.getUTCFullYear(), month: shifted.getUTCMonth() + 1, day: shifted.getUTCDate() };
}

/**
 * The `GET /revenue` query for a Revenue lens window ending at `now`: today by the hour, the
 * last 7 or 30 days (today included) by the day. The window starts at the first moment of its
 * first day in `timeZone` (inclusive) and ends at `now` (inclusive, as apps/api reads it), so a
 * sale at the start of the day counts and one after `now` has not happened yet.
 */
export function revenueQuery(period: RevenuePeriod, now: Date = new Date(), timeZone: string = STORE_TIME_ZONE): RevenueQuery {
  const first = dateBefore(now.getTime(), WINDOW_DAYS[period] - 1, timeZone);
  return {
    period: period === REVENUE_PERIOD.Today ? REVENUE_GRAIN.Hourly : REVENUE_GRAIN.Daily,
    start: new Date(startOfDay(first, timeZone)).toISOString(),
    end: now.toISOString(),
  };
}

/** `?period=…&start=…&end=…` for `query`. */
export function revenueSearch(query: RevenueQuery): string {
  return new URLSearchParams({ period: query.period, start: query.start, end: query.end }).toString();
}

const windowFormat = new Map<string, Intl.DateTimeFormat>();

/** A window read, in the store's time zone and named: "Oct 18, 00:00 – 13:16 UTC". */
export function formatWindow(start: string, end: string, timeZone: string = STORE_TIME_ZONE): string {
  let format = windowFormat.get(timeZone);
  if (!format) {
    format = new Intl.DateTimeFormat(LOCALE, {
      timeZone,
      month: "short",
      day: "numeric",
      hour: "2-digit",
      minute: "2-digit",
      hourCycle: "h23",
      timeZoneName: "short",
    });
    windowFormat.set(timeZone, format);
  }
  return format.formatRange(new Date(start), new Date(end));
}
