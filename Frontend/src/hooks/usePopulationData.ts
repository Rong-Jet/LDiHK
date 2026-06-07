import { useQuery } from '@tanstack/react-query';
import { apiRoutes, authHeaders, jsonHeaders } from '../lib/api';

export interface DistributionRow {
  hours: number;
  density: number;
}

export interface DecileRow {
  date: string;
  user: number;
  median: number | null;
  top10: number | null;
  bottom10: number | null;
  customPercentileHours: number | null;
}

export interface HourlyAverageRow {
  hour: string;
  populationAvg: number | null;
  userAvg: number | null;
}

export interface PopulationQueryResult {
  ready: boolean;
  /** true when the backend served real population comparison data, false when unavailable */
  hasPopulationData?: boolean;
  userPercentile: number | null;
  userDailyAverageHours: number | null;
  includeSynthetic: boolean;
  customPercentile: number;
  distribution: DistributionRow[];
  deciles: DecileRow[];
  hourlyAverages: HourlyAverageRow[];
}

const fetchPopulationData = async (
  platforms: string[],
  startDate: string,
  endDate: string,
  includeSynthetic: boolean,
  customPercentile: number,
  sessionToken: string,
  visibleStartDate: string
): Promise<PopulationQueryResult> => {
  const res = await fetch(apiRoutes.population(), {
    method: 'POST',
    headers: {
      ...jsonHeaders,
      ...authHeaders(sessionToken),
    },
    body: JSON.stringify({
      platforms,
      startDate,
      endDate,
      includeSynthetic,
      customPercentile,
      visibleStartDate
    })
  });

  if (!res.ok) {
    throw new Error('Failed to fetch population analytics');
  }

  return res.json();
};

export function usePopulationData(
  platforms: string[],
  startDate: string,
  endDate: string,
  includeSynthetic: boolean,
  customPercentile: number,
  isReady: boolean,
  sessionToken: string | null,
  visibleStartDate: string
) {
  return useQuery<PopulationQueryResult>({
    queryKey: ['population', platforms.join(','), startDate, endDate, includeSynthetic, customPercentile, sessionToken, visibleStartDate],
    queryFn: () => fetchPopulationData(platforms, startDate, endDate, includeSynthetic, customPercentile, sessionToken || '', visibleStartDate),
    enabled: isReady && !!startDate && !!endDate && !!sessionToken && platforms.length > 0,
  });
}
