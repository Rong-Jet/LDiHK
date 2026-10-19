import React, { useEffect, useMemo, useState } from 'react';
import { QueryClientProvider, useQuery } from '@tanstack/react-query';
import {
  RefreshCw, BarChart3, Database, ShieldAlert,
  Clock, Activity, Info, Sparkles, AlertCircle, Bed, BookOpen,
  ChevronRight, Heart, AlertTriangle, Filter, ChevronDown, ChevronUp,
  Calendar
} from 'lucide-react';
import {
  AreaChart, Area, XAxis, YAxis, Tooltip, ResponsiveContainer,
  CartesianGrid, ReferenceLine
} from 'recharts';
import ConsoleShell from './ConsoleShell';
import { useBackendStatus } from '../hooks/useBackendStatus';
import { useConsoleSession } from '../hooks/useConsoleSession';
import { describeApiError, fetchRiskReference, postQuery, QUERY_LIMIT_MAX, usesLocalMockApi } from '../lib/api';
import { ProfileCard } from './ProfileCard';
import { COMPARABLE_PLATFORMS, describeComparisonGroup, hasProfile, platformList } from '../lib/profile';
import type { PopulationSource } from '../lib/api';
import { coefficientsFor, riskScore, type CohortReference } from '../lib/riskModel';
import {
  addDays,
  DATE_PRESETS,
  daysInclusive,
  defaultRangeForBounds,
  detectPreset,
  getPresetRange,
  maxYmd,
} from '../lib/dates';
import { createConsoleQueryClient } from '../lib/queryClient';

interface QueryRow {
  date: string;
  hour: number;
  event_count: number;
  estimated_watch_seconds: number;
}

/**
 * The wellness model needs date x hour buckets. One year is 8,760 rows per
 * platform, within the backend's 10,000-row limit, so longer ranges are
 * analysed over their most recent year.
 */
const RISK_ANALYSIS_MAX_DAYS = 365;

function RiskDashboardContent() {
  const backend = useBackendStatus();
  const session = useConsoleSession({ backendReady: backend.isReady });
  const { dateBounds, sessionToken, timeZone } = session;
  // The score uses the platforms that can be compared with the population.
  const readyPlatforms = useMemo(
    () => session.readyPlatforms.filter((platform) => usesLocalMockApi || COMPARABLE_PLATFORMS.includes(platform)),
    [session.readyPlatforms]
  );
  // Days the user's selected platforms actually cover (no score outside them).
  const coverage = useMemo(() => {
    const spans = readyPlatforms
      .map((platform) => session.datasets[platform])
      .map((summary) => [summary?.watch_min_date ?? summary?.min_date, summary?.watch_max_date ?? summary?.max_date])
      .filter((span): span is [string, string] => !!span[0] && !!span[1]);
    if (spans.length === 0) return null;
    return { start: spans.map((span) => span[0]).sort()[0], end: spans.map((span) => span[1]).sort().slice(-1)[0] };
  }, [readyPlatforms, session.datasets]);
  const [populationSource, setPopulationSource] = useState<PopulationSource>('total');
  const [showAdvancedFilters, setShowAdvancedFilters] = useState(false);

  // Empty until /api/me delivered the real date bounds (no hardcoded ranges).
  const [startDate, setStartDate] = useState('');
  const [endDate, setEndDate] = useState('');

  // A different LDiHK-ID starts from a clean view.
  useEffect(() => {
    setStartDate('');
    setEndDate('');
  }, [sessionToken]);

  const boundsKey = dateBounds ? `${dateBounds.minDate}|${dateBounds.maxDate}` : '';
  useEffect(() => {
    if (!dateBounds) return;
    const { start, end } = defaultRangeForBounds(dateBounds);
    setStartDate(start);
    setEndDate(end);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [boundsKey]);

  const analysisStart = useMemo(() => (
    startDate && endDate ? maxYmd(startDate, addDays(endDate, -(RISK_ANALYSIS_MAX_DAYS - 1))) : startDate
  ), [startDate, endDate]);
  const isAnalysisClamped = !!startDate && analysisStart !== startDate;
  const analysisDays = analysisStart && endDate ? daysInclusive(analysisStart, endDate) : 0;

  // Hourly-daily watch records for the wellness analysis, summed over platforms.
  const {
    data: detailedUsageData,
    isLoading: isDetailedLoading,
    error: detailedError,
    refetch: refetchDetailed,
  } = useQuery<{ rows: QueryRow[] }>({
    queryKey: ['riskUsage', sessionToken, readyPlatforms.join(','), analysisStart, endDate, timeZone],
    queryFn: async ({ signal }) => {
      const results = await Promise.all(readyPlatforms.map((platform) => postQuery<QueryRow>(
        sessionToken as string,
        {
          dataset: `${platform}_usage`,
          metrics: ['event_count', 'estimated_watch_seconds'],
          dimensions: ['date', 'hour'],
          filters: { start_date: analysisStart, end_date: endDate },
          options: {
            include_zero_buckets: true,
            limit: Math.min(QUERY_LIMIT_MAX, analysisDays * 24),
            timezone: timeZone,
          },
        },
        signal
      )));

      const combinedMap: { [key: string]: QueryRow } = {};
      results.forEach(({ rows }) => {
        rows.forEach((r) => {
          const key = `${r.date}_${r.hour}`;
          if (!combinedMap[key]) {
            combinedMap[key] = { date: r.date, hour: r.hour, event_count: 0, estimated_watch_seconds: 0 };
          }
          combinedMap[key].event_count += r.event_count || 0;
          combinedMap[key].estimated_watch_seconds += r.estimated_watch_seconds || 0;
        });
      });
      return { rows: Object.values(combinedMap) };
    },
    enabled: backend.isReady && !!sessionToken && readyPlatforms.length > 0 && !!analysisStart && !!endDate,
  });

  // Preset Date range selection, relative to the newest day with data.
  const referenceDate = dateBounds?.maxDate ?? endDate;
  const activePreset = useMemo(
    () => detectPreset(startDate, endDate, referenceDate, dateBounds?.minDate),
    [startDate, endDate, referenceDate, dateBounds?.minDate]
  );

  const applyPreset = (preset: string) => {
    if (!referenceDate) return;
    const { start, end } = getPresetRange(preset, referenceDate, dateBounds?.minDate);
    setStartDate(start);
    setEndDate(end);
  };

  const handleResetView = () => {
    setShowAdvancedFilters(false);
    if (dateBounds) {
      const { start, end } = defaultRangeForBounds(dateBounds);
      setStartDate(start);
      setEndDate(end);
    }
  };

  // RISK COMPUTATION ENGINE (Wellness Score calculation)
  // Age and sex: score inputs are measured against the user's cohort.
  const compareWith = hasProfile(session.profile) ? 'cohort' : 'everyone';
  const coefficients = useMemo(() => coefficientsFor(session.profile), [session.profile]);
  const { data: referenceData } = useQuery({
    queryKey: ['riskReference', sessionToken, analysisStart, endDate, compareWith, readyPlatforms.join(','), populationSource],
    queryFn: ({ signal }) => fetchRiskReference(
      sessionToken as string,
      { startDate: analysisStart, endDate, compareWith, platforms: readyPlatforms, populationSource },
      signal,
    ),
    enabled: backend.isReady && !!sessionToken && !!analysisStart && !!endDate && compareWith === 'cohort',
    // Without reference values the score is simply not cohort-adjusted.
    retry: 1,
  });
  const cohortReference = useMemo<CohortReference | null>(() => (
    compareWith === 'cohort' && referenceData?.ready && referenceData.cohort && referenceData.overall
      && referenceData.comparisonGroup?.basis === 'cohort'
      ? { cohort: referenceData.cohort, overall: referenceData.overall }
      : null
  ), [compareWith, referenceData]);
  const referenceGroupLabel = describeComparisonGroup(referenceData?.comparisonGroup);

  const riskAnalysisResult = useMemo(() => {
    // Rely strictly on backend mock API endpoints to calculate wellness metrics consistently

    // Live mode query processing
    if (!detailedUsageData?.rows || detailedUsageData.rows.length === 0) {
      return {
        timelineData: [],
        currentRiskScore: 0,
        previousRiskScore: 0,
        trendType: 'stable' as const,
        trendLabel: 'Stable',
        trendColor: 'text-brand-navy/60 bg-brand-navy/5 border-brand-navy/10',
        trendDiff: 0,
        avgVolume: 0,
        avgLateNight: 0,
        avgFragmentation: 0,
        isEmptyLive: true
      };
    }

    // Group records by Date
    const dailyMap: { [dateStr: string]: QueryRow[] } = {};
    detailedUsageData.rows.forEach(r => {
      if (!dailyMap[r.date]) {
        dailyMap[r.date] = [];
      }
      dailyMap[r.date].push(r);
    });

    const dates = Object.keys(dailyMap).sort();

    const timelineData = dates.map((dateStr, dayIdx) => {
      const hoursData = dailyMap[dateStr];

      let ytSeconds = 0;
      let ytLateNightSeconds = 0;
      let activeHoursCount = 0;

      hoursData.forEach(h => {
        ytSeconds += h.estimated_watch_seconds;
        if (h.hour >= 23 || h.hour <= 4) {
          ytLateNightSeconds += h.estimated_watch_seconds;
        }
        if (h.estimated_watch_seconds >= 300) {
          activeHoursCount++;
        }
      });

      const ytHours = ytSeconds / 3600;
      const ytLateNightHours = ytLateNightSeconds / 3600;

      const fragmentationIndex = activeHoursCount / 24;
      // Measured against the user's cohort when one is known (see riskModel.ts).
      const riskScorePercent = parseFloat(riskScore(
        { hours: ytHours, lateNightHours: ytLateNightHours, fragmentation: fragmentationIndex },
        coefficients,
        cohortReference,
      ).toFixed(1));

      return {
        date: dateStr,
        riskScore: riskScorePercent,
        volume: parseFloat(ytHours.toFixed(2)),
        lateNightHours: parseFloat(ytLateNightHours.toFixed(2)),
        fragmentation: Math.round(fragmentationIndex * 100),
      };
    });

    // Only days inside the user's own history: no zeros (and no low "risk")
    // before their export starts or after it ends.
    const visibleTimelineData = timelineData.filter(d => (
      d.date >= analysisStart && d.date <= endDate
      && (!coverage || (d.date >= coverage.start && d.date <= coverage.end))
    ));
    const visibleTotalDays = visibleTimelineData.length;
    const currentPeriodData = visibleTimelineData.slice(Math.max(0, visibleTotalDays - 7));
    const previousPeriodData = visibleTimelineData.slice(Math.max(0, visibleTotalDays - 14), Math.max(0, visibleTotalDays - 7));

    const avgCurrentRisk = currentPeriodData.length > 0
      ? currentPeriodData.reduce((sum, d) => sum + d.riskScore, 0) / currentPeriodData.length
      : 0;

    const avgPreviousRisk = previousPeriodData.length > 0
      ? previousPeriodData.reduce((sum, d) => sum + d.riskScore, 0) / previousPeriodData.length
      : avgCurrentRisk;

    const diff = avgCurrentRisk - avgPreviousRisk;

    let trendType: 'strongly_up' | 'weakly_up' | 'stable' | 'weakly_down' | 'strongly_down' = 'stable';
    let trendLabel = 'Stable';
    let trendColor = 'text-brand-navy/60 bg-brand-navy/5 border-brand-navy/10';

    if (diff >= 10.0) {
      trendType = 'strongly_up';
      trendLabel = 'Strongly Upward';
      trendColor = 'text-red-600 bg-red-50 border-red-200';
    } else if (diff >= 3.0) {
      trendType = 'weakly_up';
      trendLabel = 'Weakly Upward';
      trendColor = 'text-amber-600 bg-amber-50 border-amber-200';
    } else if (diff <= -10.0) {
      trendType = 'strongly_down';
      trendLabel = 'Strongly Downward';
      trendColor = 'text-brand-teal bg-brand-teal/10 border-brand-teal/20';
    } else if (diff <= -3.0) {
      trendType = 'weakly_down';
      trendLabel = 'Weakly Downward';
      trendColor = 'text-emerald-600 bg-emerald-50 border-emerald-200';
    }

    const avgVolume = currentPeriodData.reduce((sum, d) => sum + d.volume, 0) / (currentPeriodData.length || 1);
    const avgLateNight = currentPeriodData.reduce((sum, d) => sum + d.lateNightHours, 0) / (currentPeriodData.length || 1);
    const avgFragmentation = currentPeriodData.reduce((sum, d) => sum + d.fragmentation, 0) / (currentPeriodData.length || 1);

    return {
      timelineData: visibleTimelineData,
      currentRiskScore: avgCurrentRisk,
      previousRiskScore: avgPreviousRisk,
      trendType,
      trendLabel,
      trendColor,
      trendDiff: diff,
      avgVolume,
      avgLateNight,
      avgFragmentation,
      isEmptyLive: false
    };
  }, [detailedUsageData, analysisStart, endDate, coefficients, cohortReference, coverage]);

  // Personalized Action Recommendation Logic (self-reflection wording)
  const personalizedRecommendation = useMemo(() => {
    if (!riskAnalysisResult || riskAnalysisResult.isEmptyLive) return null;

    const { avgLateNight, avgVolume, avgFragmentation, currentRiskScore } = riskAnalysisResult;

    let primaryFactor = '';
    let recommendationTitle = '';
    let recommendationText = '';
    let studyCitation = '';

    const professionalNotice = currentRiskScore >= 60
      ? 'Note: Because your wellness index is higher, we highly recommend consulting a trained medical or healthcare professional for supportive, expert guidance.'
      : '';

    if (avgLateNight >= 0.75) {
      primaryFactor = 'circadian';
      recommendationTitle = 'Late-Night Activity Shift';
      recommendationText = `Your watch patterns show significant late-night usage (${avgLateNight.toFixed(1)} hrs/night). High-stimulus screen time past 11:00 PM is known to delay biological sleep phase baselines. ${professionalNotice}`;
      studyCitation = 'Kelly et al. (2018) indicates that sleep quality and late-night digital activities are primary variables correlating screen usage with mood fluctuations.';
    }
    else if (avgVolume >= 3.0) {
      primaryFactor = 'volume';
      recommendationTitle = 'Elevated Daily Duration';
      recommendationText = `Your daily screen exposure averages ${avgVolume.toFixed(1)} hours. Consuming high volumes of digital media can displace offline focus and recovery blocks. ${professionalNotice}`;
      studyCitation = 'Riehm et al. (2019) demonstrated that spending over 3 hours daily on social platforms correlates with higher stress and mood regulation challenges.';
    }
    else if (avgFragmentation >= 35) {
      primaryFactor = 'fragmented';
      recommendationTitle = 'Frequent Usage Checks';
      recommendationText = 'Your watch sessions are highly fragmented throughout the day, suggesting frequent checking cycles. This pattern can contribute to mental fatigue and attention switching. ' + professionalNotice;
      studyCitation = 'Godard & Holtzman (2023) meta-analysis suggests that highly fragmented checking behaviors correlate with higher self-reported anxiety scores.';
    }
    else {
      primaryFactor = 'stable';
      recommendationTitle = 'Balanced Usage Parameters';
      recommendationText = 'Your social media duration, frequency, and sleep alignment currently reside within balanced thresholds. Continue prioritizing focused work and screen-free routines. ' + professionalNotice;
      studyCitation = 'Lin et al. (2016) establishes that maintaining balanced daily usage volumes supports emotional stability and cognitive focus.';
    }

    return {
      primaryFactor,
      recommendationTitle,
      recommendationText,
      studyCitation
    };
  }, [riskAnalysisResult]);


  const content = (
      <div className="space-y-6 text-left">
        {sessionToken && (
          <ProfileCard
            profile={session.profile}
            onSave={session.saveProfile}
            comparisonGroup={referenceData?.ready ? referenceData.comparisonGroup : null}
          />
        )}

        {/* Medical Disclaimer Banner */}
        <div className="bg-amber-50 border border-amber-200 rounded-3xl p-5 text-amber-900 text-xs leading-relaxed flex gap-3 relative overflow-hidden">
          <div className="absolute left-0 top-0 bottom-0 w-1 bg-amber-500"></div>
          <Info className="w-5 h-5 text-amber-600 shrink-0 mt-0.5" />
          <div>
            <span className="font-extrabold uppercase tracking-wider text-[10px] block mb-1 text-amber-800">Self-Reflection & Personal Interest Disclaimer</span>
            This section is for personal interest, self-reflection, and informational purposes only. It is calculated to the best of our knowledge based on public research correlations. <strong>This does not constitute medical advice or a clinical diagnosis.</strong> If you are experiencing distress, anxiety, low mood, or any other health concerns, please consult a trained healthcare professional for expert advice.
          </div>
        </div>

        {isAnalysisClamped && (
          <div className="bg-brand-teal/10 border border-brand-teal/25 rounded-2xl px-4 py-3 text-brand-navy text-xs leading-relaxed flex gap-2 items-center">
            <Clock className="w-4 h-4 text-brand-teal shrink-0" />
            The wellness analysis covers the most recent 12 months of the selected range ({analysisStart} to {endDate}).
          </div>
        )}

        {/* Empty Live warning if user runs live mode but database query returns empty */}
        {!isDetailedLoading && !detailedError && riskAnalysisResult?.isEmptyLive && (
          <div className="bg-brand-peach/10 border border-brand-peach/25 rounded-3xl p-5 text-brand-navy text-xs leading-relaxed flex gap-3">
            <AlertTriangle className="w-5 h-5 text-brand-peach shrink-0 mt-0.5" />
            <div>
              <span className="font-extrabold uppercase tracking-wider text-[10px] block mb-0.5 text-brand-peach">Live Database Returned Empty Rows</span>
              The live API query did not return any watch logs for the selected date range. Ensure you have uploaded YouTube Takeout files that cover this range to display wellness metrics.
            </div>
          </div>
        )}

        {/* Top Banner introducing the Wellness Analysis */}
        <div className="bg-gradient-to-r from-brand-navy to-brand-navy/90 text-white rounded-[32px] p-6 sm:p-8 relative overflow-hidden shadow-lg border border-brand-navy/25">
          <div className="absolute right-0 bottom-0 w-64 h-64 bg-brand-teal/20 rounded-full blur-3xl pointer-events-none"></div>
          <div className="absolute left-1/3 top-0 w-48 h-48 bg-brand-peach/15 rounded-full blur-2xl pointer-events-none"></div>

          <div className="relative z-10 flex flex-col md:flex-row md:items-center justify-between gap-6">
            <div className="space-y-2 flex-grow">
              <div className="inline-flex items-center gap-2 px-3 py-1 rounded-full bg-white/10 border border-white/15 text-[10px] font-extrabold uppercase tracking-wider">
                <Heart className="w-3.5 h-3.5 text-brand-peach fill-brand-peach animate-pulse" />
                Self-Reflection Wellness Model {usesLocalMockApi && '(Simulated)'}
              </div>
              <h2 className="text-2xl sm:text-3xl font-black tracking-tight leading-tight">
                Screen Habit Wellness Assessment
              </h2>
              <p className="text-xs text-white/70 max-w-2xl leading-relaxed pt-1">
                Correlating daily watch session durations and night watch patterns to map a digital wellness index.
              </p>
            </div>
          </div>
        </div>

        {/* Risk KPI Metrics Grid */}
        <div className="grid grid-cols-1 md:grid-cols-3 gap-6">

          {/* Card 1: Core Stress/Wellness Index */}
          <div className="bg-white p-6 rounded-3xl border border-brand-navy/10 shadow-sm flex flex-col justify-between relative overflow-hidden min-h-[180px]">
            <div className="absolute top-0 right-0 p-4 opacity-10">
              <Heart className="w-24 h-24 text-brand-teal" />
            </div>

            <div className="space-y-1 relative z-10">
              <span className="text-[10px] uppercase tracking-wider font-extrabold text-brand-navy/50 block">Current Scoring</span>
              <h4 className="text-sm font-extrabold text-brand-navy">Wellness Stress Index</h4>
            </div>

            <div className="py-2 flex items-baseline gap-2 relative z-10">
              {isDetailedLoading ? (
                <span className="text-5xl font-black text-brand-navy/30 animate-pulse">--%</span>
              ) : riskAnalysisResult && !riskAnalysisResult.isEmptyLive ? (
                <>
                  <span className={`text-6xl font-black tracking-tight ${
                    riskAnalysisResult.currentRiskScore >= 60
                      ? 'text-brand-peach'
                      : riskAnalysisResult.currentRiskScore >= 30
                      ? 'text-amber-500'
                      : 'text-brand-teal'
                  }`}>
                    {Math.round(riskAnalysisResult.currentRiskScore)}%
                  </span>
                  <span className="text-xs font-bold text-brand-navy/50 uppercase">Score</span>
                </>
              ) : (
                <span className="text-xs text-brand-navy/40">No data available.</span>
              )}
            </div>

            <div className="pt-3 border-t border-brand-navy/5 flex justify-between items-center text-xs relative z-10">
              <span className="font-semibold text-brand-navy/60">Wellness Rating:</span>
              {riskAnalysisResult && !riskAnalysisResult.isEmptyLive && (
                <span className={`font-black uppercase tracking-wider text-[10px] px-2 py-0.5 rounded ${
                  riskAnalysisResult.currentRiskScore >= 60
                    ? 'bg-brand-peach/10 text-brand-peach'
                    : riskAnalysisResult.currentRiskScore >= 30
                    ? 'bg-amber-100 text-amber-600'
                    : 'bg-brand-teal/10 text-brand-teal'
                }`}>
                  {riskAnalysisResult.currentRiskScore >= 60
                    ? 'Elevated Stress'
                    : riskAnalysisResult.currentRiskScore >= 30
                    ? 'Moderate baseline'
                    : 'Balanced baseline'}
                </span>
              )}
            </div>
          </div>

          {/* Card 2: Wellness Trend */}
          <div className="bg-white p-6 rounded-3xl border border-brand-navy/10 shadow-sm flex flex-col justify-between min-h-[180px]">
            <div className="space-y-1">
              <span className="text-[10px] uppercase tracking-wider font-extrabold text-brand-navy/50 block">Current Trend</span>
              <h4 className="text-sm font-extrabold text-brand-navy">Screen Habit Trend</h4>
            </div>

            <div className="py-2 relative z-10 flex flex-col justify-center">
              {isDetailedLoading ? (
                <span className="text-xl font-black text-brand-navy/30 animate-pulse">Analyzing...</span>
              ) : riskAnalysisResult && !riskAnalysisResult.isEmptyLive ? (
                <div className="space-y-1">
                  <div className="flex items-center gap-2">
                    <div className={`px-2.5 py-0.5 rounded text-[10px] font-black uppercase tracking-wider border ${riskAnalysisResult.trendColor}`}>
                      {riskAnalysisResult.trendLabel}
                    </div>
                    <span className="text-[10px] font-mono font-bold text-brand-navy/60">
                      {riskAnalysisResult.trendDiff > 0 ? '+' : ''}{riskAnalysisResult.trendDiff.toFixed(1)}% vs last week
                    </span>
                  </div>
                  <p className="text-[11px] text-brand-navy/60 leading-relaxed pt-1">
                    {riskAnalysisResult.trendType === 'strongly_up' && 'Weekly checks suggest a rising stress pattern. Screen rest advised.'}
                    {riskAnalysisResult.trendType === 'weakly_up' && 'Minor upward shift. Consider scheduling offline blocks.'}
                    {riskAnalysisResult.trendType === 'stable' && 'Trend is stable. Good balance of screen duration.'}
                    {riskAnalysisResult.trendType === 'weakly_down' && 'Downward wellness trend. Keep maintaining current boundaries.'}
                    {riskAnalysisResult.trendType === 'strongly_down' && 'Strong positive development. Wellness index has improved.'}
                  </p>
                </div>
              ) : (
                <span className="text-xs text-brand-navy/40">Pending data.</span>
              )}
            </div>

            <div className="pt-3 border-t border-brand-navy/5 flex justify-between items-center text-xs">
              <span className="font-semibold text-brand-navy/60">Primary Source:</span>
              <span className="font-extrabold text-brand-teal uppercase text-[10px]">
                {usesLocalMockApi ? 'Simulated Data' : readyPlatforms.join(' + ')}
              </span>
            </div>
          </div>

          {/* Card 3: Key Digital Biomarkers */}
          <div className="bg-white p-6 rounded-3xl border border-brand-navy/10 shadow-sm flex flex-col justify-between min-h-[180px]">
            <div className="space-y-1">
              <span className="text-[10px] uppercase tracking-wider font-extrabold text-brand-navy/50 block">Biomarkers</span>
              <h4 className="text-sm font-extrabold text-brand-navy">Average Daily Metrics</h4>
            </div>

            <div className="grid grid-cols-3 gap-2 py-2 text-center">
              <div>
                <span className="text-[9px] uppercase tracking-wider font-bold text-brand-navy/50 block">Volume</span>
                <span className="text-sm font-black text-brand-navy block mt-0.5">
                  {riskAnalysisResult && !riskAnalysisResult.isEmptyLive ? `${riskAnalysisResult.avgVolume.toFixed(1)}h` : '--'}
                </span>
              </div>
              <div>
                <span className="text-[9px] uppercase tracking-wider font-bold text-brand-peach/80 block flex items-center justify-center gap-0.5">
                  <Bed className="w-2.5 h-2.5 text-brand-peach" /> Night
                </span>
                <span className="text-sm font-black text-brand-peach block mt-0.5">
                  {riskAnalysisResult && !riskAnalysisResult.isEmptyLive ? `${riskAnalysisResult.avgLateNight.toFixed(1)}h` : '--'}
                </span>
              </div>
              <div>
                <span className="text-[9px] uppercase tracking-wider font-bold text-brand-teal block">Fragm.</span>
                <span className="text-sm font-black text-brand-teal block mt-0.5">
                  {riskAnalysisResult && !riskAnalysisResult.isEmptyLive ? `${Math.round(riskAnalysisResult.avgFragmentation)}%` : '--'}
                </span>
              </div>
            </div>

            <div className="pt-3 border-t border-brand-navy/5 text-[9px] text-brand-navy/50 text-center">
              {cohortReference && referenceGroupLabel
                ? `Typical for ${referenceGroupLabel}: ${cohortReference.cohort.dailyHours.toFixed(1)}h · ${cohortReference.cohort.lateNightHours.toFixed(1)}h · ${Math.round(cohortReference.cohort.fragmentation * 100)}%`
                : 'Metrics calculated over current selected range.'}
            </div>
          </div>

        </div>

        {/* Timeline Chart Box */}
        {detailedError ? (
          <div className="bg-brand-peach/10 border border-brand-peach/30 rounded-3xl p-6 text-center text-brand-navy flex flex-col items-center gap-3">
            <ShieldAlert className="w-10 h-10 text-brand-peach" />
            <h4 className="font-bold">Failed to load wellness timeline data</h4>
            <p className="text-xs text-brand-navy/70">{describeApiError(detailedError)}</p>
            <button
              onClick={() => refetchDetailed()}
              className="px-4 py-2 rounded-xl bg-brand-navy text-white text-xs font-bold cursor-pointer"
            >
              Retry Request
            </button>
          </div>
        ) : isDetailedLoading ? (
          <div className="h-[400px] flex items-center justify-center bg-white border border-brand-navy/10 rounded-3xl">
            <RefreshCw className="w-8 h-8 animate-spin text-brand-teal" />
          </div>
        ) : riskAnalysisResult && !riskAnalysisResult.isEmptyLive ? (
          <div className="bg-white border border-brand-navy/10 rounded-3xl p-6 shadow-sm space-y-6 animate-scale-up">

            {/* Timeline Chart Header */}
            <div className="flex flex-col sm:flex-row sm:items-center sm:justify-between gap-4 pb-4 border-b border-brand-navy/5">
              <div className="flex items-center gap-3">
                <div className="w-10 h-10 rounded-xl bg-brand-navy/5 flex items-center justify-center text-brand-navy">
                  <Activity className="w-5 h-5" />
                </div>
                <div>
                  <h3 className="font-bold text-brand-navy text-lg">Stress Index Timeline</h3>
                  <p className="text-xs text-brand-navy/50">Wellness index trend mapped day-by-day across the timeframe.</p>
                </div>
              </div>

              <div className="flex flex-wrap items-center gap-3">
                {/* Preset Controls */}
                <div className="flex items-center bg-brand-beige/60 p-1 rounded-xl border border-brand-navy/5 flex-wrap">
                  {DATE_PRESETS.map((preset) => (
                    <button
                      key={preset}
                      onClick={() => applyPreset(preset)}
                      className={`px-2.5 py-1.5 rounded-lg text-xs font-bold transition-all uppercase cursor-pointer ${
                        activePreset === preset
                          ? 'bg-brand-navy text-white shadow-sm'
                          : 'text-brand-navy/60 hover:text-brand-navy'
                      }`}
                    >
                      {preset === 'all' ? 'All' : preset}
                    </button>
                  ))}
                </div>

                {/* Advanced Timeframe Trigger */}
                <button
                  onClick={() => setShowAdvancedFilters(!showAdvancedFilters)}
                  className={`px-4 py-2.5 rounded-xl text-xs font-bold border transition-all flex items-center gap-1.5 cursor-pointer ${
                    showAdvancedFilters
                      ? 'bg-brand-navy text-white border-brand-navy shadow-sm'
                      : 'bg-white border-brand-navy/10 text-brand-navy/70 hover:border-brand-navy/20'
                  }`}
                >
                  <Filter className="w-3.5 h-3.5" />
                  Time Filters
                  {showAdvancedFilters ? <ChevronUp className="w-3.5 h-3.5" /> : <ChevronDown className="w-3.5 h-3.5" />}
                </button>
              </div>
            </div>

            {/* Advanced Custom Timeframe Section */}
            {showAdvancedFilters && (
              <div className="grid grid-cols-1 gap-6 bg-brand-beige/25 p-5 rounded-2xl border border-brand-navy/5 text-left mb-4">
                <div className="space-y-2">
                  <label className="text-[10px] uppercase tracking-wider font-extrabold text-brand-navy/60 flex items-center gap-1.5">
                    <Calendar className="w-3.5 h-3.5 text-brand-teal" />
                    Timeline Timeframe
                  </label>
                  <div className="flex items-center gap-2">
                    <input
                      type="date"
                      value={startDate}
                      min={dateBounds?.minDate}
                      max={dateBounds?.maxDate}
                      onChange={(e) => setStartDate(e.target.value)}
                      className="bg-white border border-brand-navy/15 rounded-xl px-3 py-2 text-xs font-bold text-brand-navy focus:outline-none focus:ring-1 focus:ring-brand-teal w-full"
                    />
                    <span className="text-brand-navy/40 text-xs font-bold">to</span>
                    <input
                      type="date"
                      value={endDate}
                      min={dateBounds?.minDate}
                      max={dateBounds?.maxDate}
                      onChange={(e) => setEndDate(e.target.value)}
                      className="bg-white border border-brand-navy/15 rounded-xl px-3 py-2 text-xs font-bold text-brand-navy focus:outline-none focus:ring-1 focus:ring-brand-teal w-full"
                    />
                  </div>
                  <span className="text-[9px] text-brand-navy/40 block">Queries backend to update chart scope.</span>
                </div>
                {!usesLocalMockApi && (
                  <div className="space-y-2">
                    <label htmlFor="risk-population-source" className="text-[10px] uppercase tracking-wider font-extrabold text-brand-navy/60 flex items-center gap-1.5">
                      <Calendar className="w-3.5 h-3.5 text-brand-teal" />
                      Reference Values From The Population's
                    </label>
                    <select
                      id="risk-population-source"
                      value={populationSource}
                      onChange={(event) => setPopulationSource(event.target.value as PopulationSource)}
                      className="w-full sm:w-auto bg-white border border-brand-navy/20 rounded-xl px-3 py-2 text-xs font-semibold text-brand-navy focus:outline-none focus:ring-2 focus:ring-brand-teal/30"
                    >
                      <option value="total">Total social media time (YouTube, TikTok, Instagram, LinkedIn)</option>
                      <option value="matching">Time on the same platforms as mine ({platformList(readyPlatforms)})</option>
                    </select>
                    <span className="text-[9px] text-brand-navy/40 block">Your score uses {platformList(readyPlatforms)}.</span>
                  </div>
                )}
              </div>
            )}

            {/* Area Chart representation */}
            <div className="h-[300px] w-full font-sans select-none">
              <ResponsiveContainer width="100%" height="100%">
                <AreaChart
                  data={riskAnalysisResult.timelineData}
                  margin={{ top: 10, right: 10, left: -20, bottom: 0 }}
                >
                  <defs>
                    <linearGradient id="riskGrad" x1="0" y1="0" x2="0" y2="1">
                      <stop offset="5%" stopColor="#EC8F8D" stopOpacity={0.4}/>
                      <stop offset="95%" stopColor="#EC8F8D" stopOpacity={0.0}/>
                    </linearGradient>
                  </defs>
                  <CartesianGrid strokeDasharray="3 3" vertical={false} stroke="#537D96" strokeOpacity={0.08} />
                  <XAxis
                    dataKey="date"
                    tickLine={false}
                    axisLine={false}
                    tickFormatter={(str) => {
                      const parts = str.split('-');
                      if (parts.length === 3) {
                        const dateObj = new Date(str);
                        const diffDays = riskAnalysisResult.timelineData.length;

                        if (diffDays > 730) {
                          return dateObj.toLocaleDateString('en-US', { year: 'numeric' });
                        }
                        if (diffDays > 30) {
                          return dateObj.toLocaleDateString('en-US', { month: 'short', year: '2-digit' });
                        }
                        return `${parts[1]}/${parts[2]}`;
                      }
                      return str;
                    }}
                    tick={{ fill: '#537D96', fontSize: 10, fontWeight: 700, opacity: 0.7 }}
                  />
                  <YAxis
                    domain={[0, 100]}
                    tickLine={false}
                    axisLine={false}
                    tickFormatter={(v) => `${v}%`}
                    tick={{ fill: '#537D96', fontSize: 10, fontWeight: 700, opacity: 0.7 }}
                  />
                  <Tooltip
                    content={({ active, payload }) => {
                      if (active && payload && payload.length) {
                        const data = payload[0].payload;
                        return (
                          <div className="bg-brand-navy text-white p-3 rounded-2xl shadow-xl border border-white/10 text-xs text-left space-y-1 font-sans">
                            <span className="font-bold block opacity-60">{data.date}</span>
                            <span className="text-base font-black text-brand-peach block">
                              Stress Index: {data.riskScore}%
                            </span>
                            <div className="pt-1.5 border-t border-white/10 space-y-0.5 text-[10px]">
                              <span className="block">Daily Screen Use: {data.volume.toFixed(1)} hrs</span>
                              <span className="block">Late-Night Hours: {data.lateNightHours.toFixed(1)} hrs</span>
                              <span className="block">Fragmentation: {data.fragmentation}% active</span>
                            </div>
                          </div>
                        );
                      }
                      return null;
                    }}
                  />
                  <Area
                    type="monotone"
                    dataKey="riskScore"
                    stroke="#EC8F8D"
                    strokeWidth={2.5}
                    fillOpacity={1}
                    fill="url(#riskGrad)"
                  />
                  <ReferenceLine y={60} stroke="#EC8F8D" strokeDasharray="3 3" label={{ value: 'Elevated Stress Threshold (60%)', fill: '#EC8F8D', fontSize: 10, position: 'top', fontWeight: 700, opacity: 0.8 }} strokeOpacity={0.5} />
                  <ReferenceLine y={30} stroke="#537D96" strokeDasharray="3 3" label={{ value: 'Balanced Threshold (30%)', fill: '#537D96', fontSize: 10, position: 'top', fontWeight: 700, opacity: 0.8 }} strokeOpacity={0.4} />
                </AreaChart>
              </ResponsiveContainer>
            </div>

          </div>
        ) : null}

        {/* Recommendations & Scientific Bibliography */}
        {riskAnalysisResult && !riskAnalysisResult.isEmptyLive && (
          <div className="grid grid-cols-1 md:grid-cols-2 gap-6 animate-scale-up">

            {/* Personalized Recommendations Box */}
            <div className="bg-white p-6 rounded-3xl border border-brand-navy/10 shadow-sm space-y-4">
              <div className="flex items-center gap-2 pb-2 border-b border-brand-navy/10">
                <Sparkles className="w-4 h-4 text-brand-teal" />
                <h3 className="font-extrabold text-brand-navy text-xs uppercase tracking-wider">Wellness Recommendations</h3>
              </div>

              {personalizedRecommendation ? (
                <div className="space-y-4 text-left">
                  <div className="p-4 rounded-2xl bg-brand-beige/25 border border-brand-navy/10 space-y-2">
                    <h4 className="font-black text-sm text-brand-navy flex items-center gap-2">
                      <AlertCircle className="w-4 h-4 text-brand-peach shrink-0" />
                      {personalizedRecommendation.recommendationTitle}
                    </h4>
                    <p className="text-xs text-brand-navy/70 leading-relaxed">
                      {personalizedRecommendation.recommendationText}
                    </p>
                  </div>

                  <div className="space-y-2">
                    <h5 className="text-[10px] uppercase tracking-wider font-extrabold text-brand-navy/50 block">Usage Action Plan:</h5>
                    <ul className="space-y-2 text-xs">
                      {personalizedRecommendation.primaryFactor === 'circadian' && (
                        <>
                          <li className="flex items-start gap-2.5">
                            <ChevronRight className="w-4 h-4 text-brand-peach shrink-0 mt-0.5" />
                            <span><strong>Establish Bedtime Rule:</strong> Silence app notifications or shut down your device after 10:30 PM.</span>
                          </li>
                          <li className="flex items-start gap-2.5">
                            <ChevronRight className="w-4 h-4 text-brand-peach shrink-0 mt-0.5" />
                            <span><strong>Night Shift Mode:</strong> Enable automatic warm colors on screen settings to block sleep-delaying blue light wavelengths.</span>
                          </li>
                        </>
                      )}
                      {personalizedRecommendation.primaryFactor === 'volume' && (
                        <>
                          <li className="flex items-start gap-2.5">
                            <ChevronRight className="w-4 h-4 text-brand-peach shrink-0 mt-0.5" />
                            <span><strong>Cap Daily Use:</strong> Utilize system screen time caps to limit excessive daily sessions.</span>
                          </li>
                          <li className="flex items-start gap-2.5">
                            <ChevronRight className="w-4 h-4 text-brand-peach shrink-0 mt-0.5" />
                            <span><strong>Focused Offline Blocks:</strong> Allocate dedicated screen-free slots for physical movement, social connection, or focus work.</span>
                          </li>
                        </>
                      )}
                      {personalizedRecommendation.primaryFactor === 'fragmented' && (
                        <>
                          <li className="flex items-start gap-2.5">
                            <ChevronRight className="w-4 h-4 text-brand-peach shrink-0 mt-0.5" />
                            <span><strong>Batch Notifications:</strong> Avoid checking apps continuously. Set scheduled intervals (e.g., lunch, dinner) to review updates.</span>
                          </li>
                          <li className="flex items-start gap-2.5">
                            <ChevronRight className="w-4 h-4 text-brand-peach shrink-0 mt-0.5" />
                            <span><strong>Clean Workspace:</strong> Keep devices out of arm's reach or in grayscale mode during study or work blocks.</span>
                          </li>
                        </>
                      )}
                      {personalizedRecommendation.primaryFactor === 'stable' && (
                        <>
                          <li className="flex items-start gap-2.5">
                            <ChevronRight className="w-4 h-4 text-brand-teal shrink-0 mt-0.5" />
                            <span><strong>Maintain Healthy Boundaries:</strong> Continue keeping sleep environments device-free.</span>
                          </li>
                          <li className="flex items-start gap-2.5">
                            <ChevronRight className="w-4 h-4 text-brand-teal shrink-0 mt-0.5" />
                            <span><strong>Regular Habits Audit:</strong> Use this dashboard to periodically check in on watch trends.</span>
                          </li>
                        </>
                      )}
                    </ul>
                  </div>

                  <div className="pt-2 text-[10px] text-brand-navy/60 italic leading-relaxed border-t border-brand-navy/5 flex gap-2">
                    <BookOpen className="w-4 h-4 text-brand-teal shrink-0 mt-0.5" />
                    <span>
                      <strong>Public Research Context:</strong> {personalizedRecommendation.studyCitation}
                    </span>
                  </div>
                </div>
              ) : (
                <span className="text-xs text-brand-navy/40">Audit your logs to load recommendations.</span>
              )}
            </div>

            {/* Scientific Bibliography Box */}
            <div className="bg-white p-6 rounded-3xl border border-brand-navy/10 shadow-sm space-y-4 text-left">
              <div className="flex items-center gap-2 pb-2 border-b border-brand-navy/10">
                <BookOpen className="w-4 h-4 text-brand-teal" />
                <h3 className="font-extrabold text-brand-navy text-xs uppercase tracking-wider">Literature Bibliography</h3>
              </div>

              <div className="h-[280px] overflow-y-auto pr-2 space-y-3.5 text-xs text-brand-navy/75 scrollbar-thin scrollbar-thumb-brand-navy/20">

                <div className="space-y-1">
                  <p className="font-extrabold text-brand-navy">Kelly, Y., Zilanawala, A., Booker, C., & Sacker, A. (2018)</p>
                  <p className="italic text-[11px] leading-relaxed">
                    Social media use and adolescent mental health: Findings from the UK Millennium Cohort Study. EClinicalMedicine, 6, 59–68.
                  </p>
                  <a href="https://doi.org/10.1016/j.eclinm.2018.12.005" target="_blank" rel="noopener noreferrer" className="text-[10px] text-brand-teal hover:underline block font-semibold">
                    https://doi.org/10.1016/j.eclinm.2018.12.005
                  </a>
                </div>

                <div className="space-y-1 border-t border-brand-navy/5 pt-3.5">
                  <p className="font-extrabold text-brand-navy">Lin, L. Y., Sidani, J. E., Shensa, A., Radovic, A., et al. (2016)</p>
                  <p className="italic text-[11px] leading-relaxed">
                    Association between social media use and depression among U.S. young adults. Depression and Anxiety, 33(4), 323–331.
                  </p>
                  <a href="https://doi.org/10.1002/da.22466" target="_blank" rel="noopener noreferrer" className="text-[10px] text-brand-teal hover:underline block font-semibold">
                    https://doi.org/10.1002/da.22466
                  </a>
                </div>

                <div className="space-y-1 border-t border-brand-navy/5 pt-3.5">
                  <p className="font-extrabold text-brand-navy">Primack, B. A., Shensa, A., Escobar-Viera, C. G., et al. (2017)</p>
                  <p className="italic text-[11px] leading-relaxed">
                    Use of multiple social media platforms and symptoms of depression and anxiety: A nationally-representative study. Computers in Human Behavior, 69, 1–9.
                  </p>
                  <a href="https://doi.org/10.1016/j.chb.2016.11.013" target="_blank" rel="noopener noreferrer" className="text-[10px] text-brand-teal hover:underline block font-semibold">
                    https://doi.org/10.1016/j.chb.2016.11.013
                  </a>
                </div>

                <div className="space-y-1 border-t border-brand-navy/5 pt-3.5">
                  <p className="font-extrabold text-brand-navy">Riehm, K. E., Feder, K. A., Tormohlen, K. N., et al. (2019)</p>
                  <p className="italic text-[11px] leading-relaxed">
                    Associations between time spent using social media and internalizing and externalizing problems among US youth. JAMA Psychiatry, 76(12), 1266–1273.
                  </p>
                  <a href="https://doi.org/10.1001/jamapsychiatry.2019.2325" target="_blank" rel="noopener noreferrer" className="text-[10px] text-brand-teal hover:underline block font-semibold">
                    https://doi.org/10.1001/jamapsychiatry.2019.2325
                  </a>
                </div>

                <div className="space-y-1 border-t border-brand-navy/5 pt-3.5">
                  <p className="font-extrabold text-brand-navy">Woodward, M. J., McGettrick, C. R., Dick, O. G., et al. (2025)</p>
                  <p className="italic text-[11px] leading-relaxed">
                    Time spent on social media and associations with mental health in young adults: Examining TikTok, Twitter, Instagram, Facebook, Youtube, Snapchat, and Reddit. Journal of Technology in Behavioral Science.
                  </p>
                  <a href="https://doi.org/10.1007/s41347-024-00474-y" target="_blank" rel="noopener noreferrer" className="text-[10px] text-brand-teal hover:underline block font-semibold">
                    https://doi.org/10.1007/s41347-024-00474-y
                  </a>
                </div>

              </div>
            </div>

          </div>
        )}

      </div>
  );

  return (
    <ConsoleShell
      activeTab="risk"
      backend={backend}
      session={session}
      onResetView={handleResetView}
      awaitingDescription="Upon file ingestion, our wellness assessment will compile habit trend timelines."
      processingDescription="Our background ingestion worker is processing your archive. This will align daily logs and compile wellness parameters."
    >
      {content}
    </ConsoleShell>
  );
}

export default function RiskDashboardContainer() {
  const [queryClient] = useState(createConsoleQueryClient);
  return (
    <QueryClientProvider client={queryClient}>
      <RiskDashboardContent />
    </QueryClientProvider>
  );
}
