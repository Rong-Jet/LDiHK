import { useQuery } from '@tanstack/react-query';
import { useMemo } from 'react';
import { postQuery, QUERY_LIMIT_MAX } from '../lib/api';
import {
  daysInclusive,
  daysOfMonthWithin,
  enumerateDays,
  enumerateMonths,
  type DateGranularity,
} from '../lib/dates';

export interface BucketRow {
  date?: string;
  month?: string;
  event_count: number;
  estimated_watch_seconds: number;
}

export interface HourlyRow {
  hour: number;
  event_count: number;
  estimated_watch_seconds: number;
}

export interface PlatformBucketResult {
  platform: string;
  rows: BucketRow[];
}

export interface PlatformHourlyResult {
  platform: string;
  rows: HourlyRow[];
}

export interface CombinedQueryResult {
  granularity: DateGranularity;
  bucketResults: PlatformBucketResult[];
  hourlyResults: PlatformHourlyResult[];
}

export interface FlattenedTimelineRecord {
  /** Bucket key: `YYYY-MM-DD` (daily) or `YYYY-MM` (monthly). */
  date: string;
  /** Calendar days represented by the bucket; monthly values are per-day averages. */
  bucketDays: number;
  youtubeHours: number;
  instagramHours: number;
  tiktokHours: number;
  spotifyHours: number;
  twitterHours: number;
  linkedinHours: number;
  youtubeEvents: number;
  instagramEvents: number;
  tiktokEvents: number;
  spotifyEvents: number;
  twitterEvents: number;
  linkedinEvents: number;
  totalHours: number;
  totalEvents: number;
}

/** Ranges longer than ~2 years are charted as monthly buckets. */
export const DAILY_TIMELINE_MAX_DAYS = 731;

export function timelineGranularity(startDate: string, endDate: string): DateGranularity {
  if (!startDate || !endDate) return 'day';
  return daysInclusive(startDate, endDate) > DAILY_TIMELINE_MAX_DAYS ? 'month' : 'day';
}

const PLATFORM_FIELDS: Record<string, { hours: keyof FlattenedTimelineRecord; events: keyof FlattenedTimelineRecord }> = {
  youtube: { hours: 'youtubeHours', events: 'youtubeEvents' },
  instagram: { hours: 'instagramHours', events: 'instagramEvents' },
  tiktok: { hours: 'tiktokHours', events: 'tiktokEvents' },
  spotify: { hours: 'spotifyHours', events: 'spotifyEvents' },
  twitter: { hours: 'twitterHours', events: 'twitterEvents' },
  linkedin: { hours: 'linkedinHours', events: 'linkedinEvents' },
};

// Runs the bucket + hour-of-day queries for every active platform. Any failed
// request rejects the whole query so the UI shows an error (never "no data").
const fetchCombinedPlatforms = async (
  platforms: string[],
  startDate: string,
  endDate: string,
  sessionToken: string,
  signal?: AbortSignal
): Promise<CombinedQueryResult> => {
  const granularity = timelineGranularity(startDate, endDate);
  if (platforms.length === 0) {
    return { granularity, bucketResults: [], hourlyResults: [] };
  }

  const bucketCount = granularity === 'day'
    ? daysInclusive(startDate, endDate)
    : enumerateMonths(startDate, endDate).length;
  const bucketLimit = Math.min(QUERY_LIMIT_MAX, bucketCount + 1);
  const filters = { start_date: startDate, end_date: endDate };

  const bucketPromises = platforms.map(async (platform) => {
    const data = await postQuery<BucketRow>(sessionToken, {
      dataset: `${platform}_usage`,
      metrics: ['event_count', 'estimated_watch_seconds'],
      dimensions: [granularity === 'day' ? 'date' : 'month'],
      filters,
      options: { limit: bucketLimit },
    }, signal);
    return { platform, rows: data.rows ?? [] };
  });

  const hourlyPromises = platforms.map(async (platform) => {
    const data = await postQuery<HourlyRow>(sessionToken, {
      dataset: `${platform}_usage`,
      metrics: ['event_count', 'estimated_watch_seconds'],
      dimensions: ['hour'],
      filters,
      options: { limit: 24 },
    }, signal);
    return { platform, rows: data.rows ?? [] };
  });

  const [bucketResults, hourlyResults] = await Promise.all([
    Promise.all(bucketPromises),
    Promise.all(hourlyPromises),
  ]);

  return { granularity, bucketResults, hourlyResults };
};

export function useAnalyticsData(
  activePlatforms: string[],
  startDate: string,
  endDate: string,
  isReady: boolean,
  sessionToken: string | null
) {
  const enabled = isReady && !!sessionToken && activePlatforms.length > 0 && !!startDate && !!endDate && startDate <= endDate;

  const { data, isLoading, error, refetch, isFetching } = useQuery<CombinedQueryResult>({
    queryKey: ['insights', activePlatforms.join(','), startDate, endDate, sessionToken],
    queryFn: ({ signal }) => fetchCombinedPlatforms(activePlatforms, startDate, endDate, sessionToken as string, signal),
    enabled,
  });

  const granularity: DateGranularity = data?.granularity ?? timelineGranularity(startDate, endDate);

  // Zero-filled buckets for the visible range. Daily buckets hold hours per
  // day; monthly buckets hold the average hours per day of that month.
  const chartData = useMemo<FlattenedTimelineRecord[]>(() => {
    if (!data?.bucketResults || !startDate || !endDate) return [];

    const keys = data.granularity === 'day' ? enumerateDays(startDate, endDate) : enumerateMonths(startDate, endDate);
    const records = new Map<string, FlattenedTimelineRecord>();
    keys.forEach((key) => {
      records.set(key, {
        date: key,
        bucketDays: data.granularity === 'day' ? 1 : Math.max(1, daysOfMonthWithin(key, startDate, endDate)),
        youtubeHours: 0,
        instagramHours: 0,
        tiktokHours: 0,
        spotifyHours: 0,
        twitterHours: 0,
        linkedinHours: 0,
        youtubeEvents: 0,
        instagramEvents: 0,
        tiktokEvents: 0,
        spotifyEvents: 0,
        twitterEvents: 0,
        linkedinEvents: 0,
        totalHours: 0,
        totalEvents: 0,
      });
    });

    data.bucketResults.forEach((result) => {
      const fields = PLATFORM_FIELDS[result.platform];
      if (!fields) return;
      result.rows.forEach((row) => {
        const key = data.granularity === 'day' ? row.date : row.month;
        const record = key ? records.get(key) : undefined;
        if (!record) return;
        const hours = parseFloat(((row.estimated_watch_seconds || 0) / 3600 / record.bucketDays).toFixed(2));
        const events = row.event_count || 0;
        (record[fields.hours] as number) += hours;
        (record[fields.events] as number) += events;
        record.totalHours += hours;
        record.totalEvents += events;
      });
    });

    return keys.map((key) => {
      const record = records.get(key) as FlattenedTimelineRecord;
      return { ...record, totalHours: parseFloat(record.totalHours.toFixed(2)) };
    });
  }, [data, startDate, endDate]);

  // Calendar days in the visible range (timezone-independent).
  const dayCount = useMemo(() => (startDate && endDate ? daysInclusive(startDate, endDate) : 1), [startDate, endDate]);

  // Total hours in scope, from raw seconds (monthly chart values are averages).
  const totalScopeHours = useMemo(() => {
    if (!data?.bucketResults) return 0;
    const seconds = data.bucketResults.reduce(
      (sum, result) => sum + result.rows.reduce((inner, row) => inner + (row.estimated_watch_seconds || 0), 0),
      0
    );
    return seconds / 3600;
  }, [data]);

  // Average daily watch time per local hour of day across the visible range.
  const hourlyHeatmapData = useMemo(() => {
    const hourlyAggregateSecs = new Array(24).fill(0);
    data?.hourlyResults?.forEach((result) => {
      result.rows.forEach((row) => {
        if (row.hour >= 0 && row.hour < 24) {
          hourlyAggregateSecs[row.hour] += row.estimated_watch_seconds || 0;
        }
      });
    });

    return hourlyAggregateSecs.map((valueInSecs, hour) => ({
      hour: `${hour.toString().padStart(2, '0')}:00`,
      value: parseFloat((valueInSecs / 3600 / dayCount).toFixed(3)),
    }));
  }, [data, dayCount]);

  return {
    chartData,
    granularity,
    hourlyHeatmapData,
    totalScopeHours,
    dayCount,
    isLoading: enabled && isLoading,
    isFetching,
    error,
    refetch,
  };
}
