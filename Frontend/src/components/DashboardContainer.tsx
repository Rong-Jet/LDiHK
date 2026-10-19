import React, { useEffect, useMemo, useRef, useState } from 'react';
import { QueryClientProvider } from '@tanstack/react-query';
import { RefreshCw, ShieldAlert } from 'lucide-react';
import ConsoleShell from './ConsoleShell';
import MainTimeline from './MainTimeline';
import DeepDive from './DeepDive';
import BehavioralHeatmap from './BehavioralHeatmap';
import { useAnalyticsData } from '../hooks/useAnalyticsData';
import { useBackendStatus } from '../hooks/useBackendStatus';
import { QUERYABLE_PLATFORMS, useConsoleSession } from '../hooks/useConsoleSession';
import { describeApiError } from '../lib/api';
import { defaultRangeForBounds, formatCalendarValue } from '../lib/dates';
import { createConsoleQueryClient } from '../lib/queryClient';

function formatSpan(startDate: string, endDate: string) {
  if (!startDate || !endDate) return '--';
  if (startDate.slice(0, 4) === endDate.slice(0, 4)) {
    return `${startDate.slice(5).replace('-', '/')} - ${endDate.slice(5).replace('-', '/')}`;
  }
  const monthYear = { month: 'short', year: 'numeric' } as const;
  return `${formatCalendarValue(startDate, monthYear)} - ${formatCalendarValue(endDate, monthYear)}`;
}

function DashboardContent() {
  const backend = useBackendStatus();
  const session = useConsoleSession({ backendReady: backend.isReady });
  const { readyPlatforms, dateBounds, datasets: summaries, sessionToken } = session;

  const [selectedDate, setSelectedDate] = useState<string | null>(null);
  const [activePlatforms, setActivePlatformsState] = useState<string[]>([]);
  const platformsTouched = useRef(false);
  // Empty until /api/me delivered the real date bounds (no hardcoded ranges).
  const [startDate, setStartDate] = useState('');
  const [endDate, setEndDate] = useState('');

  const setActivePlatforms = (platforms: string[]) => {
    platformsTouched.current = true;
    setActivePlatformsState(platforms);
  };

  // A different LDiHK-ID starts from a clean view.
  useEffect(() => {
    platformsTouched.current = false;
    setSelectedDate(null);
    setStartDate('');
    setEndDate('');
    setActivePlatformsState([]);
  }, [sessionToken]);

  // Default the platform selection to every platform that has data.
  const readyKey = readyPlatforms.join(',');
  useEffect(() => {
    setActivePlatformsState((current) => (
      !platformsTouched.current || !current.some((platform) => readyPlatforms.includes(platform))
        ? readyPlatforms
        : current
    ));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [readyKey]);

  // Initial visible window from the dataset bounds reported by /api/me.
  const boundsKey = dateBounds ? `${dateBounds.minDate}|${dateBounds.maxDate}` : '';
  useEffect(() => {
    if (!dateBounds) return;
    const { start, end } = defaultRangeForBounds(dateBounds);
    setStartDate(start);
    setEndDate(end);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [boundsKey]);

  const timelineDatasets = useMemo(() => Object.fromEntries(
    QUERYABLE_PLATFORMS.map((platform) => {
      const summary = summaries[platform];
      return [platform, {
        status: readyPlatforms.includes(platform) ? 'READY' : 'NOT_UPLOADED',
        min_date: summary?.min_date ?? undefined,
        max_date: summary?.max_date ?? undefined,
        watch_min_date: summary?.watch_min_date ?? undefined,
        watch_max_date: summary?.watch_max_date ?? undefined,
      }];
    })
  ), [summaries, readyPlatforms]);

  // Only query active platforms that actually have data
  const platformsToQuery = useMemo(
    () => activePlatforms.filter((platform) => readyPlatforms.includes(platform)),
    [activePlatforms, readyPlatforms]
  );

  // Analytics Ingest Query (gated on a ready backend and real date bounds)
  const {
    chartData,
    granularity,
    hourlyHeatmapData,
    totalScopeHours,
    dayCount,
    isLoading: isInsightsLoading,
    error: insightsError,
    refetch: refetchInsights,
  } = useAnalyticsData(platformsToQuery, startDate, endDate, backend.isReady && !!dateBounds, sessionToken);

  // Find dataset record for selected date
  const selectedDayData = useMemo(() => {
    if (!selectedDate) return undefined;
    return chartData.find((d) => d.date === selectedDate);
  }, [chartData, selectedDate]);

  const handleResetView = () => {
    setSelectedDate(null);
    platformsTouched.current = false;
    setActivePlatformsState(readyPlatforms);
    if (dateBounds) {
      const { start, end } = defaultRangeForBounds(dateBounds);
      setStartDate(start);
      setEndDate(end);
    }
  };

  const content = (
    <div className="space-y-6">
      {/* Dynamic Stats Row */}
      <div className="grid grid-cols-2 lg:grid-cols-4 gap-4">
        <div className="bg-white p-5 rounded-2xl border border-brand-navy/10 shadow-sm">
          <span className="text-[10px] uppercase tracking-wider font-extrabold text-brand-navy/50 block">Ingested Channels</span>
          <span className="text-2xl font-black text-brand-navy mt-1 block">
            {readyPlatforms.length} {readyPlatforms.length === 1 ? 'Platform' : 'Platforms'}
          </span>
        </div>
        <div className="bg-white p-5 rounded-2xl border border-brand-navy/10 shadow-sm">
          <span className="text-[10px] uppercase tracking-wider font-extrabold text-brand-teal mt-1 block">Active Filters</span>
          <span className="text-2xl font-black text-brand-teal mt-1 block">
            {platformsToQuery.length} of {readyPlatforms.length}
          </span>
        </div>
        <div className="bg-white p-5 rounded-2xl border border-brand-navy/10 shadow-sm">
          <span className="text-[10px] uppercase tracking-wider font-extrabold text-brand-navy/50 block">Time Span</span>
          <span className="text-xl font-black text-brand-navy mt-1 block truncate" title={`${startDate} to ${endDate} (${session.timeZone})`}>
            {formatSpan(startDate, endDate)}
          </span>
        </div>
        <div className="bg-white p-5 rounded-2xl border border-brand-navy/10 shadow-sm">
          <span className="text-[10px] uppercase tracking-wider font-extrabold text-brand-navy/50 block">Database Storage</span>
          <span className="text-2xl font-black text-brand-peach mt-1 block">Anonymous</span>
        </div>
      </div>

      {insightsError ? (
        <div className="bg-brand-peach/10 border border-brand-peach/30 rounded-2xl p-6 text-center text-brand-navy flex flex-col items-center gap-3">
          <ShieldAlert className="w-10 h-10 text-brand-peach" />
          <h4 className="font-bold">Failed to load analytics details</h4>
          <p className="text-xs text-brand-navy/70 max-w-md">{describeApiError(insightsError)}</p>
          <button
            onClick={() => refetchInsights()}
            className="px-4 py-2 rounded-xl bg-brand-navy text-white text-xs font-bold cursor-pointer"
          >
            Retry Request
          </button>
        </div>
      ) : isInsightsLoading || !startDate ? (
        <div className="h-[400px] flex items-center justify-center bg-white border border-brand-navy/10 rounded-3xl">
          <RefreshCw className="w-8 h-8 animate-spin text-brand-teal" />
        </div>
      ) : (
        <div className="space-y-6">
          {/* Timeline and Deep Dive Grid */}
          <div className="grid grid-cols-1 xl:grid-cols-3 gap-6">
            <div className="xl:col-span-2">
              <MainTimeline
                data={chartData}
                activePlatforms={activePlatforms}
                setActivePlatforms={setActivePlatforms}
                selectedDate={selectedDate}
                onSelectDate={setSelectedDate}
                startDate={startDate}
                endDate={endDate}
                setDateRange={(start, end) => {
                  setStartDate(start);
                  setEndDate(end);
                }}
                datasets={timelineDatasets}
                dateBounds={dateBounds}
                granularity={granularity}
              />
            </div>
            <div>
              <DeepDive selectedDate={selectedDate} dayData={selectedDayData} />
            </div>
          </div>

          {/* Heatmap Section (hours are local to the browser timezone) */}
          <BehavioralHeatmap
            data={hourlyHeatmapData}
            activePlatforms={platformsToQuery}
            totalScopeHours={totalScopeHours}
            dayCount={dayCount}
          />
        </div>
      )}
    </div>
  );

  return (
    <ConsoleShell
      activeTab="dashboard"
      backend={backend}
      session={session}
      onResetView={handleResetView}
      awaitingDescription="Upon file ingestion, our analytics console will poll the indexing service to normalize raw segments into timeline parameters."
      processingDescription="Our background ingestion worker is processing your archive. This will flatten daily history logs, map hourly watch boundaries, and build timeline analytics."
    >
      {content}
    </ConsoleShell>
  );
}

export default function DashboardContainer() {
  const [queryClient] = useState(createConsoleQueryClient);
  return (
    <QueryClientProvider client={queryClient}>
      <DashboardContent />
    </QueryClientProvider>
  );
}
