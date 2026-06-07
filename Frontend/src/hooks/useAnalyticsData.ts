import { useQuery } from '@tanstack/react-query';
import { useMemo } from 'react';

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
  smaHours: number;
}

const IS_MOCK_MODE = import.meta.env.PUBLIC_MOCK_API === 'true';
const API_BASE = IS_MOCK_MODE ? '' : (import.meta.env.PUBLIC_API_URL || '');

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

  // 1. Fetch daily records
  const dailyPromises = platforms.map(async (platform) => {
    const res = await fetch(`${API_BASE}/api/query`, {
      method: 'POST',
      headers: { 
        'Content-Type': 'application/json',
        'Authorization': `Bearer ${sessionToken}`
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
    if (!res.ok) throw new Error(`Daily query failed for ${platform}`);
    const data = await res.json();
    return { platform, rows: data.rows as DailyRow[] };
  });

  // 2. Fetch hourly aggregates
  const hourlyPromises = platforms.map(async (platform) => {
    const res = await fetch(`${API_BASE}/api/query`, {
      method: 'POST',
      headers: { 
        'Content-Type': 'application/json',
        'Authorization': `Bearer ${sessionToken}`
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
    if (!res.ok) throw new Error(`Hourly query failed for ${platform}`);
    const data = await res.json();
    return { platform, rows: data.rows as HourlyRow[] };
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
  trendlinePeriod: number,
  isReady: boolean,
  sessionToken: string = 'mock-session-ldihkid-12345'
) {
  // Pad the startDate by 90 days to eliminate the timeline boundary edge effect (peak at start of graph)
  const paddedStartDate = useMemo(() => {
    if (!startDate) return '';
    const dateObj = new Date(startDate);
    dateObj.setDate(dateObj.getDate() - 90);
    return dateObj.toISOString().split('T')[0];
  }, [startDate]);

  // Query to fetch data only when uploader is completed and API is READY
  const { data, isLoading, error, refetch } = useQuery<CombinedQueryResult>({
    queryKey: ['insights', activePlatforms.join(','), paddedStartDate, endDate, sessionToken],
    queryFn: () => fetchCombinedPlatforms(activePlatforms, paddedStartDate, endDate, sessionToken),
    enabled: isReady && activePlatforms.length > 0 && !!paddedStartDate && !!endDate,
  });

  // Merge daily records, apply timeline-duration-scaled smoothing, and calculate SMA
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
        smaHours: 0,
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

    // Determine a sensible smoothing rolling window based on the VISIBLE range length (not padded range)
    const [y1, m1, d1] = startDate.split('-').map(Number);
    const [y2, m2, d2] = endDate.split('-').map(Number);
    const startUTC = Date.UTC(y1, m1 - 1, d1);
    const endUTC = Date.UTC(y2, m2 - 1, d2);
    const visibleDaysCount = Math.max(1, Math.round((endUTC - startUTC) / (1000 * 3600 * 24)) + 1);

    let smoothWindow = 1; // raw (no smoothing) by default
    if (visibleDaysCount > 1825) {
      smoothWindow = 60; // 60-day rolling average for 5Y+
    } else if (visibleDaysCount > 365) {
      smoothWindow = 30; // 30-day rolling average for 1Y+
    } else if (visibleDaysCount > 30) {
      smoothWindow = 7;  // 7-day rolling average for >30 Days
    }

    // Apply rolling average smoothing to raw platform curves
    const smoothed = rawMapped.map((record, index) => {
      if (smoothWindow <= 1) return record;

      const start = Math.max(0, index - smoothWindow + 1);
      const count = index - start + 1;
      
      let ytSum = 0, igSum = 0, tkSum = 0, spSum = 0, twSum = 0, liSum = 0;
      let ytEv = 0, igEv = 0, tkEv = 0, spEv = 0, twEv = 0, liEv = 0;

      for (let j = start; j <= index; j++) {
        ytSum += rawMapped[j].youtubeHours;
        igSum += rawMapped[j].instagramHours;
        tkSum += rawMapped[j].tiktokHours;
        spSum += rawMapped[j].spotifyHours;
        twSum += rawMapped[j].twitterHours;
        liSum += rawMapped[j].linkedinHours;

        ytEv += rawMapped[j].youtubeEvents;
        igEv += rawMapped[j].instagramEvents;
        tkEv += rawMapped[j].tiktokEvents;
        spEv += rawMapped[j].spotifyEvents;
        twEv += rawMapped[j].twitterEvents;
        liEv += rawMapped[j].linkedinEvents;
      }

      return {
        date: record.date,
        youtubeHours: parseFloat((ytSum / count).toFixed(2)),
        instagramHours: parseFloat((igSum / count).toFixed(2)),
        tiktokHours: parseFloat((tkSum / count).toFixed(2)),
        spotifyHours: parseFloat((spSum / count).toFixed(2)),
        twitterHours: parseFloat((twSum / count).toFixed(2)),
        linkedinHours: parseFloat((liSum / count).toFixed(2)),
        youtubeEvents: Math.round(ytEv / count),
        instagramEvents: Math.round(igEv / count),
        tiktokEvents: Math.round(tkEv / count),
        spotifyEvents: Math.round(spEv / count),
        twitterEvents: Math.round(twEv / count),
        linkedinEvents: Math.round(liEv / count),
        totalHours: parseFloat(((ytSum + igSum + tkSum + spSum + twSum + liSum) / count).toFixed(2)),
        totalEvents: Math.round((ytEv + igEv + tkEv + spEv + twEv + liEv) / count),
        smaHours: 0,
      };
    });

    // 3. Compute the Simple Moving Average (SMA) of total watch hours using dynamic trendlinePeriod
    const allSMA = smoothed.map((record, index) => {
      let sum = 0;
      let count = 0;

      const windowSize = trendlinePeriod;
      const start = Math.max(0, index - windowSize + 1);
      
      for (let i = start; i <= index; i++) {
        sum += smoothed[i].totalHours;
        count++;
      }

      const smaHours = count > 0 ? parseFloat((sum / count).toFixed(2)) : 0;

      return {
        ...record,
        smaHours,
      };
    });

    // 4. Filter only visible dates to return to the graphs
    return allSMA.filter((record) => record.date >= startDate && record.date <= endDate);
  }, [data, trendlinePeriod, startDate, endDate]);

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

  // Aggregate hourly watch time and divide by number of days to get average daily watchtime per hour (based on visible dates)
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
