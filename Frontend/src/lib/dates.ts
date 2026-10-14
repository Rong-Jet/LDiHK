/**
 * Calendar-date helpers. Dates in this app are `YYYY-MM-DD` strings that the
 * backend has already bucketed in the requested timezone, so they must be
 * treated as plain calendar days: never parse them with `new Date('YYYY-MM-DD')`
 * and format them in local time (that shows the previous day west of UTC).
 * Everything here works in UTC milliseconds purely as a day counter.
 */

const DAY_MS = 24 * 60 * 60 * 1000;
const YMD_PATTERN = /^(\d{4})-(\d{2})-(\d{2})$/;
const YM_PATTERN = /^(\d{4})-(\d{2})$/;

export type DateGranularity = 'day' | 'month';

export function isYmd(value: unknown): boolean {
  return typeof value === 'string' && YMD_PATTERN.test(value);
}

export function isYearMonth(value: unknown): boolean {
  return typeof value === 'string' && YM_PATTERN.test(value);
}

export function ymdToUtcMs(ymd: string): number {
  const [year, month, day] = ymd.split('-').map(Number);
  return Date.UTC(year, month - 1, day);
}

export function utcMsToYmd(ms: number): string {
  return new Date(ms).toISOString().slice(0, 10);
}

export function addDays(ymd: string, days: number): string {
  return utcMsToYmd(ymdToUtcMs(ymd) + days * DAY_MS);
}

export function addYears(ymd: string, years: number): string {
  const [year, month, day] = ymd.split('-').map(Number);
  return utcMsToYmd(Date.UTC(year + years, month - 1, day));
}

/** Number of calendar days in [start, end], inclusive (min 1). */
export function daysInclusive(start: string, end: string): number {
  return Math.max(1, Math.round((ymdToUtcMs(end) - ymdToUtcMs(start)) / DAY_MS) + 1);
}

export function minYmd(a: string, b: string): string {
  return a <= b ? a : b;
}

export function maxYmd(a: string, b: string): string {
  return a >= b ? a : b;
}

export function clampYmd(value: string, min: string, max: string): string {
  return minYmd(maxYmd(value, min), max);
}

export function enumerateDays(start: string, end: string): string[] {
  const days: string[] = [];
  for (let ms = ymdToUtcMs(start), endMs = ymdToUtcMs(end); ms <= endMs; ms += DAY_MS) {
    days.push(utcMsToYmd(ms));
  }
  return days;
}

export function monthKey(ymd: string): string {
  return ymd.slice(0, 7);
}

export function enumerateMonths(start: string, end: string): string[] {
  const months: string[] = [];
  let [year, month] = start.split('-').map(Number);
  const [endYear, endMonth] = end.split('-').map(Number);
  while (year < endYear || (year === endYear && month <= endMonth)) {
    months.push(`${year}-${String(month).padStart(2, '0')}`);
    month += 1;
    if (month > 12) {
      month = 1;
      year += 1;
    }
  }
  return months;
}

/** Days of month `ym` (YYYY-MM) that fall inside [start, end]. */
export function daysOfMonthWithin(ym: string, start: string, end: string): number {
  const [year, month] = ym.split('-').map(Number);
  const monthStart = utcMsToYmd(Date.UTC(year, month - 1, 1));
  const monthEnd = utcMsToYmd(Date.UTC(year, month, 0));
  const from = maxYmd(monthStart, start);
  const to = minYmd(monthEnd, end);
  return from > to ? 0 : daysInclusive(from, to);
}

const formatterCache = new Map<string, Intl.DateTimeFormat>();

function utcFormatter(options: Intl.DateTimeFormatOptions): Intl.DateTimeFormat {
  const cacheKey = JSON.stringify(options);
  let formatter = formatterCache.get(cacheKey);
  if (!formatter) {
    formatter = new Intl.DateTimeFormat('en-US', { ...options, timeZone: 'UTC' });
    formatterCache.set(cacheKey, formatter);
  }
  return formatter;
}

/** Formats a YYYY-MM-DD or YYYY-MM calendar value without any timezone shift. */
export function formatCalendarValue(value: string, options: Intl.DateTimeFormatOptions): string {
  if (isYmd(value)) return utcFormatter(options).format(new Date(ymdToUtcMs(value)));
  if (isYearMonth(value)) return utcFormatter(options).format(new Date(ymdToUtcMs(`${value}-01`)));
  return value;
}

export function formatMonthLabel(ym: string): string {
  return formatCalendarValue(ym, { month: 'long', year: 'numeric' });
}

/** X-axis tick label for timeline charts. */
export function formatAxisLabel(value: string, pointCount: number): string {
  if (isYearMonth(value)) {
    return pointCount > 36
      ? formatCalendarValue(value, { year: 'numeric' })
      : formatCalendarValue(value, { month: 'short', year: '2-digit' });
  }
  if (!isYmd(value)) return value;
  if (pointCount > 730) return formatCalendarValue(value, { year: 'numeric' });
  if (pointCount > 30) return formatCalendarValue(value, { month: 'short', year: '2-digit' });
  return `${value.slice(5, 7)}/${value.slice(8, 10)}`;
}

export const DATE_PRESETS = ['1D', '7D', '15D', '30D', '1Y', '5Y', 'all'] as const;
export type DatePreset = (typeof DATE_PRESETS)[number];

/** Preset range ending at `referenceDate`, clamped to the dataset's first day. */
export function getPresetRange(preset: string, referenceDate: string, minDate?: string | null) {
  let start = referenceDate;
  if (preset === '7D') start = addDays(referenceDate, -6);
  else if (preset === '15D') start = addDays(referenceDate, -14);
  else if (preset === '30D') start = addDays(referenceDate, -29);
  else if (preset === '1Y') start = addDays(addYears(referenceDate, -1), 1);
  else if (preset === '5Y') start = addDays(addYears(referenceDate, -5), 1);
  else if (preset === 'all') start = minDate || referenceDate;

  if (minDate && start < minDate) start = minDate;
  return { start, end: referenceDate };
}

export function detectPreset(
  startDate: string,
  endDate: string,
  referenceDate: string,
  minDate?: string | null
): DatePreset | 'custom' {
  if (!startDate || endDate !== referenceDate) return 'custom';
  for (const preset of DATE_PRESETS) {
    if (getPresetRange(preset, referenceDate, minDate).start === startDate) return preset;
  }
  return 'custom';
}

export interface DateBounds {
  minDate: string;
  maxDate: string;
}

/** Initial visible window: the last 30 days for long histories, otherwise everything. */
export function defaultRangeForBounds(bounds: DateBounds): { start: string; end: string } {
  if (daysInclusive(bounds.minDate, bounds.maxDate) > 91) {
    return getPresetRange('30D', bounds.maxDate, bounds.minDate);
  }
  return { start: bounds.minDate, end: bounds.maxDate };
}

/** IANA timezone of the browser, used for local date/hour buckets. */
export function getBrowserTimeZone(): string {
  try {
    return Intl.DateTimeFormat().resolvedOptions().timeZone || 'UTC';
  } catch {
    return 'UTC';
  }
}
