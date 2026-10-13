import { CURRENCY, LOCALE } from "@/constants/i18n.constant";

/** Number and date formatting in `LOCALE`. Money is in `CURRENCY`. */
export type Formatters = {
  /** Short money for tiles and labels: "$12.4K". */
  money: (value: number) => string;
  /** Exact money for tooltips. */
  moneyExact: (value: number) => string;
  count: (value: number) => string;
  /** 0..1 as a percentage. */
  percent: (value: number) => string;
  /** A signed change such as "+8%"; 0 shows without a sign. */
  change: (value: number) => string;
  /** A signed count such as "+12" or "-12"; 0 shows without a sign. */
  delta: (value: number) => string;
  hour: (iso: string) => string;
  day: (iso: string) => string;
};

function formatters(locale: string, currency: string): Formatters {
  const money = new Intl.NumberFormat(locale, { style: "currency", currency, notation: "compact", minimumFractionDigits: 0, maximumFractionDigits: 1 });
  const moneyExact = new Intl.NumberFormat(locale, { style: "currency", currency });
  const count = new Intl.NumberFormat(locale, { maximumFractionDigits: 0 });
  const percent = new Intl.NumberFormat(locale, { style: "percent", maximumFractionDigits: 1 });
  const change = new Intl.NumberFormat(locale, { style: "percent", maximumFractionDigits: 1, signDisplay: "exceptZero" });
  const delta = new Intl.NumberFormat(locale, { maximumFractionDigits: 0, signDisplay: "exceptZero" });
  const hour = new Intl.DateTimeFormat(locale, { hour: "2-digit", minute: "2-digit", hour12: false });
  const day = new Intl.DateTimeFormat(locale, { day: "numeric", month: "short" });

  return {
    money: (value) => money.format(value),
    moneyExact: (value) => moneyExact.format(value),
    count: (value) => count.format(value),
    percent: (value) => percent.format(value),
    change: (value) => change.format(value),
    delta: (value) => delta.format(value),
    hour: (iso) => hour.format(new Date(iso)),
    day: (iso) => day.format(new Date(iso)),
  };
}

/** The app's formatters. */
export const format: Formatters = formatters(LOCALE, CURRENCY);

/** Relative change from `previous` to `current`, or null when there is nothing to compare with. */
export function relativeChange(current: number, previous: number): number | null {
  return previous ? (current - previous) / previous : null;
}
