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
  useSyntheticData: boolean;
  customPercentile: number;
  distribution: DistributionRow[];
  deciles: DecileRow[];
  hourlyAverages: HourlyAverageRow[];
}

const fetchPopulationData = async (
  startDate: string,
  endDate: string,
  useSyntheticData: boolean,
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
      startDate,
      endDate,
      useSyntheticData,
      customPercentile
    })
  });

  if (!res.ok) {
    throw new Error('Failed to fetch population analytics');
  }

  return res.json();
};

export function usePopulationData(
  startDate: string,
  endDate: string,
  useSyntheticData: boolean,
  customPercentile: number,
  isReady: boolean,
  sessionToken: string | null
) {
  return useQuery<PopulationQueryResult>({
    queryKey: ['population', startDate, endDate, useSyntheticData, customPercentile, sessionToken],
    queryFn: () => fetchPopulationData(startDate, endDate, useSyntheticData, customPercentile, sessionToken || ''),
    enabled: isReady && !!startDate && !!endDate && !!sessionToken,
  });
}
