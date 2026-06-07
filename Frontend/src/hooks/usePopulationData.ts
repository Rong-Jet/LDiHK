import { useQuery } from '@tanstack/react-query';
import { apiRoutes, authHeaders, jsonHeaders } from '../lib/api';

export interface DistributionRow {
  hours: number;
  density: number;
}

export interface DecileRow {
  date: string;
  user: number;
  median: number;
  top10: number;
  bottom10: number;
  customPercentileHours: number;
}

export interface HourlyAverageRow {
  hour: string;
  populationAvg: number;
  userAvg: number;
}

export interface PopulationQueryResult {
  ready: boolean;
  userPercentile: number;
  userDailyAverageHours: number;
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
  sessionToken: string
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
      customPercentile
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
  sessionToken: string | null
) {
  return useQuery<PopulationQueryResult>({
    queryKey: ['population', platforms.join(','), startDate, endDate, includeSynthetic, customPercentile, sessionToken],
    queryFn: () => fetchPopulationData(platforms, startDate, endDate, includeSynthetic, customPercentile, sessionToken || ''),
    enabled: isReady && !!startDate && !!endDate && !!sessionToken && platforms.length > 0,
  });
}
