import { useQuery } from '@tanstack/react-query';

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

const IS_MOCK_MODE = import.meta.env.PUBLIC_MOCK_API === 'true';
const API_BASE = IS_MOCK_MODE ? '' : (import.meta.env.PUBLIC_API_URL || '');

const fetchPopulationData = async (
  platforms: string[],
  startDate: string,
  endDate: string,
  useSyntheticData: boolean,
  customPercentile: number,
  sessionToken: string
): Promise<PopulationQueryResult> => {
  const res = await fetch('/api/population', {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
      'Authorization': `Bearer ${sessionToken}`
    },
    body: JSON.stringify({
      platforms,
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
  platforms: string[],
  startDate: string,
  endDate: string,
  useSyntheticData: boolean,
  customPercentile: number,
  isReady: boolean,
  sessionToken: string | null
) {
  return useQuery<PopulationQueryResult>({
    queryKey: ['population', platforms.join(','), startDate, endDate, useSyntheticData, customPercentile, sessionToken],
    queryFn: () => fetchPopulationData(platforms, startDate, endDate, useSyntheticData, customPercentile, sessionToken || ''),
    enabled: isReady && !!startDate && !!endDate && !!sessionToken && platforms.length > 0,
  });
}
