import { useQuery } from '@tanstack/react-query';
import { fetchPopulationJson, type ComparisonGroup } from '../lib/api';

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
  /** true when the response carries real population comparison data */
  hasPopulationData: boolean;
  /** Why there is no comparison: 'no_user_data' or 'insufficient_population'. */
  reason?: string;
  message?: string;
  /** Number of other people (real and synthetic) in the comparison. */
  populationSize: number | null;
  /** Whom the user was compared with (missing from older backends). */
  comparisonGroup: ComparisonGroup | null;
  /** Days the synthetic profiles were generated for (used as a weekday baseline). */
  syntheticBaseline: { startDate: string; endDate: string } | null;
  userPercentile: number | null;
  userDailyAverageHours: number | null;
  includeSynthetic: boolean;
  customPercentile: number;
  distribution: DistributionRow[];
  deciles: DecileRow[];
  hourlyAverages: HourlyAverageRow[];
}

type PopulationResponse = Partial<PopulationQueryResult> & { ready?: boolean };

/**
 * POST /api/population. In live mode this goes straight to the backend (no
 * Netlify function in between, so a waking server is not cut off after 10 s);
 * in mock mode it resolves to the local Astro mock route.
 */
const fetchPopulationData = async (
  platforms: string[],
  startDate: string,
  endDate: string,
  includeSynthetic: boolean,
  customPercentile: number,
  sessionToken: string,
  visibleStartDate: string,
  compareWith: 'cohort' | 'everyone',
  signal?: AbortSignal
): Promise<PopulationQueryResult> => {
  const data = await fetchPopulationJson<PopulationResponse>(
    sessionToken,
    { platforms, startDate, endDate, includeSynthetic, customPercentile, visibleStartDate, compareWith },
    signal
  );
  const ready = data.ready === true;
  return {
    ready,
    hasPopulationData: data.hasPopulationData ?? ready,
    reason: data.reason,
    message: data.message,
    populationSize: data.populationSize ?? null,
    comparisonGroup: data.comparisonGroup ?? null,
    syntheticBaseline: data.syntheticBaseline ?? null,
    userPercentile: data.userPercentile ?? null,
    userDailyAverageHours: data.userDailyAverageHours ?? null,
    includeSynthetic: data.includeSynthetic ?? includeSynthetic,
    customPercentile: data.customPercentile ?? customPercentile,
    distribution: data.distribution ?? [],
    deciles: data.deciles ?? [],
    hourlyAverages: data.hourlyAverages ?? [],
  };
};

export function usePopulationData(
  platforms: string[],
  startDate: string,
  endDate: string,
  includeSynthetic: boolean,
  customPercentile: number,
  isReady: boolean,
  sessionToken: string | null,
  visibleStartDate: string,
  /** `cohort`: people of similar age range and sex (falls back to everyone). */
  compareWith: 'cohort' | 'everyone' = 'everyone'
) {
  return useQuery<PopulationQueryResult>({
    queryKey: ['population', platforms.join(','), startDate, endDate, includeSynthetic, customPercentile, sessionToken, visibleStartDate, compareWith],
    queryFn: ({ signal }) => fetchPopulationData(
      platforms, startDate, endDate, includeSynthetic, customPercentile, sessionToken || '', visibleStartDate, compareWith, signal
    ),
    enabled: isReady && !!startDate && !!endDate && !!sessionToken && platforms.length > 0,
  });
}
