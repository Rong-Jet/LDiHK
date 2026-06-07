import { useQuery } from '@tanstack/react-query';
import { useMemo } from 'react';
import { apiRoutes, authHeaders, jsonHeaders } from '../lib/api';

export interface DailyRow {
  date: string;
  event_count: number;
  estimated_watch_seconds: number;
}

export interface HourlyRow {
  hour: number;
  event_count: number;
  estimated_watch_seconds: number;
}

export interface PlatformDailyResult {
  platform: string;
  rows: DailyRow[];
}

export interface PlatformHourlyResult {
  platform: string;
  rows: HourlyRow[];
}

export interface CombinedQueryResult {
  dailyResults: PlatformDailyResult[];
  hourlyResults: PlatformHourlyResult[];
}

export interface FlattenedTimelineRecord {
  date: string;
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

// Fetch helper that runs POST queries in parallel for active platforms with date range filters
const fetchCombinedPlatforms = async (
  platforms: string[],
  startDate: string,
  endDate: string,
  sessionToken: string
): Promise<CombinedQueryResult> => {
  if (platforms.length === 0) {
    return { dailyResults: [], hourlyResults: [] };
  }

  const emptyDailyResult = (platform: string): PlatformDailyResult => ({
    platform,
    rows: [],
  });
  const emptyHourlyResult = (platform: string): PlatformHourlyResult => ({
    platform,
    rows: [],
  });

  // 1. Fetch daily records for the visible interval only.
  const dailyPromises = platforms.map(async (platform) => {
    try {
      const res = await fetch(apiRoutes.query(), {
        method: 'POST',
        headers: {
          ...jsonHeaders,
          ...authHeaders(sessionToken),
        },
        body: JSON.stringify({
          dataset: `${platform}_usage`,
          metrics: ['event_count', 'estimated_watch_seconds'],
          dimensions: ['date'],
          filters: {
            start_date: startDate,
            end_date: endDate,
          },
        }),
      });
      if (!res.ok) return emptyDailyResult(platform);
      const data = await res.json();
      return { platform, rows: data.rows as DailyRow[] };
    } catch {
      return emptyDailyResult(platform);
    }
  });

  // 2. Fetch hourly aggregates for the visible interval.
  const hourlyPromises = platforms.map(async (platform) => {
    try {
      const res = await fetch(apiRoutes.query(), {
        method: 'POST',
        headers: {
          ...jsonHeaders,
          ...authHeaders(sessionToken),
        },
        body: JSON.stringify({
          dataset: `${platform}_usage`,
          metrics: ['event_count', 'estimated_watch_seconds'],
          dimensions: ['hour'],
          filters: {
            start_date: startDate,
            end_date: endDate,
          },
        }),
      });
      if (!res.ok) return emptyHourlyResult(platform);
      const data = await res.json();
      return { platform, rows: data.rows as HourlyRow[] };
    } catch {
      return emptyHourlyResult(platform);
    }
  });

  const [dailyResults, hourlyResults] = await Promise.all([
    Promise.all(dailyPromises),
    Promise.all(hourlyPromises),
  ]);

  return { dailyResults, hourlyResults };
};

export function useAnalyticsData(
  activePlatforms: string[],
  startDate: string,
  endDate: string,
  isReady: boolean,
  sessionToken: string = 'mock-session-ldihkid-12345'
) {
  // Query to fetch data only when uploader is completed and API is READY
  const { data, isLoading, error, refetch } = useQuery<CombinedQueryResult>({
    queryKey: ['insights', activePlatforms.join(','), startDate, endDate, sessionToken],
    queryFn: () => fetchCombinedPlatforms(activePlatforms, startDate, endDate, sessionToken),
    enabled: isReady && activePlatforms.length > 0 && !!startDate && !!endDate,
  });

  // Merge daily records without smoothing so temporal graphs show the raw selected interval.
  const chartData = useMemo<FlattenedTimelineRecord[]>(() => {
    if (!data?.dailyResults || data.dailyResults.length === 0) return [];

    const dateSet = new Set<string>();
    data.dailyResults.forEach((res) => {
      res.rows.forEach((row) => dateSet.add(row.date));
    });

    const sortedDates = Array.from(dateSet).sort();

    // Map each date to a single combined stacked record (raw)
    const rawMapped = sortedDates.map((date) => {
      const record: FlattenedTimelineRecord = {
        date,
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
      };

      data.dailyResults.forEach((res) => {
        const row = res.rows.find((r) => r.date === date);
        if (row) {
          const hrs = parseFloat((row.estimated_watch_seconds / 3600).toFixed(2));
          const evts = row.event_count;

          if (res.platform === 'youtube') {
            record.youtubeHours = hrs;
            record.youtubeEvents = evts;
          } else if (res.platform === 'instagram') {
            record.instagramHours = hrs;
            record.instagramEvents = evts;
          } else if (res.platform === 'tiktok') {
            record.tiktokHours = hrs;
            record.tiktokEvents = evts;
          } else if (res.platform === 'spotify') {
            record.spotifyHours = hrs;
            record.spotifyEvents = evts;
          } else if (res.platform === 'twitter') {
            record.twitterHours = hrs;
            record.twitterEvents = evts;
          } else if (res.platform === 'linkedin') {
            record.linkedinHours = hrs;
            record.linkedinEvents = evts;
          }

          record.totalHours += hrs;
          record.totalEvents += evts;
        }
      });

      record.totalHours = parseFloat(record.totalHours.toFixed(2));
      return record;
    });

    return rawMapped.filter((record) => record.date >= startDate && record.date <= endDate);
  }, [data, startDate, endDate]);

  // Timezone-independent day count (based on visible dates)
  const dayCount = useMemo(() => {
    if (!startDate || !endDate) return 1;
    const [y1, m1, d1] = startDate.split('-').map(Number);
    const [y2, m2, d2] = endDate.split('-').map(Number);
    const startUTC = Date.UTC(y1, m1 - 1, d1);
    const endUTC = Date.UTC(y2, m2 - 1, d2);
    const diffMs = endUTC - startUTC;
    return Math.max(1, Math.round(diffMs / (1000 * 3600 * 24)) + 1);
  }, [startDate, endDate]);

  // Calculate total scope hours across all daily results of active platforms (based on visible dates)
  const totalScopeHours = useMemo(() => {
    if (!chartData || chartData.length === 0) return 0;
    return chartData.reduce((sum, record) => sum + record.totalHours, 0);
  }, [chartData]);

  // Aggregate hourly watch time and divide by number of days to get average daily watchtime per hour (based on visible range)
  const hourlyHeatmapData = useMemo(() => {
    const hourlyAggregateSecs = new Array(24).fill(0);

    if (data?.hourlyResults && data.hourlyResults.length > 0) {
      data.hourlyResults.forEach((res) => {
        res.rows.forEach((row) => {
          if (row.hour >= 0 && row.hour < 24) {
            hourlyAggregateSecs[row.hour] += row.estimated_watch_seconds;
          }
        });
      });
    }

    // Convert seconds to average daily hours
    return hourlyAggregateSecs.map((valueInSecs, hour) => {
      const totalHours = valueInSecs / 3600;
      const averageHours = parseFloat((totalHours / dayCount).toFixed(3)); 
      return {
        hour: `${hour.toString().padStart(2, '0')}:00`,
        value: averageHours, 
      };
    });
  }, [data, dayCount]);

  return {
    chartData,
    hourlyHeatmapData,
    totalScopeHours,
    dayCount,
    isLoading,
    error,
    refetch,
  };
}
