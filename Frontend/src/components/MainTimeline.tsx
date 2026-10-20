import React, { useState, useMemo } from 'react';
import {
  AreaChart, Area, XAxis, YAxis, CartesianGrid,
  Tooltip, ResponsiveContainer
} from 'recharts';
import { Calendar, Filter, Layers, CheckSquare, Square, ChevronDown, ChevronUp } from 'lucide-react';
import type { FlattenedTimelineRecord } from '../hooks/useAnalyticsData';
import { usesLocalMockApi } from '../lib/api';
import {
  DATE_PRESETS,
  detectPreset,
  formatAxisLabel,
  formatCalendarValue,
  getPresetRange,
  isYearMonth,
  type DateGranularity,
} from '../lib/dates';

interface MainTimelineProps {
  data: FlattenedTimelineRecord[];
  activePlatforms: string[];
  setActivePlatforms: (platforms: string[]) => void;
  selectedDate: string | null;
  onSelectDate: (date: string) => void;

  // Date range filters for the timeline query
  startDate: string;
  endDate: string;
  setDateRange: (start: string, end: string) => void;

  datasets?: Record<string, { status: string; min_date?: string; max_date?: string; watch_min_date?: string; watch_max_date?: string }>;
  dateBounds?: { minDate: string; maxDate: string } | null;
  /** `month` when the range is long enough to be charted as monthly averages. */
  granularity?: DateGranularity;
}

const ALL_PLATFORMS = ['YouTube', 'Instagram', 'TikTok', 'Spotify', 'Twitter', 'LinkedIn'];

const PLATFORM_COLORS: Record<string, string> = {
  youtube: '#537D96',   // brand-navy
  instagram: '#EC8F8D', // brand-peach
  tiktok: '#44A194',    // brand-teal
  spotify: '#5EAF81',   // brand-green
  twitter: '#8ba6b8',   // light navy
  linkedin: '#66b8ad',  // light teal
};

const PLATFORM_LABELS: Record<string, string> = {
  youtubeHours: 'YouTube',
  instagramHours: 'Instagram',
  tiktokHours: 'TikTok',
  spotifyHours: 'Spotify',
  twitterHours: 'Twitter/X',
  linkedinHours: 'LinkedIn',
  totalHours: 'Total Active Time',
};

const FALLBACK_REFERENCE_DATE = '2026-06-06';

const PLATFORM_HOURS_KEYS: Record<string, keyof FlattenedTimelineRecord> = {
  youtube: 'youtubeHours',
  instagram: 'instagramHours',
  tiktok: 'tiktokHours',
  spotify: 'spotifyHours',
  twitter: 'twitterHours',
  linkedin: 'linkedinHours',
};

/** Whether a day (`YYYY-MM-DD`) or month (`YYYY-MM`) bucket lies within a platform's data. */
export function bucketWithinData(bucket: string, minDate: string, maxDate: string): boolean {
  if (isYearMonth(bucket)) return bucket >= minDate.slice(0, 7) && bucket <= maxDate.slice(0, 7);
  return bucket >= minDate && bucket <= maxDate;
}

/**
 * Chart rows where a platform's hours are `null` outside the days its watch
 * data covers (inside, a day without use stays 0). A stacked area draws its
 * outline along the stack even at 0, so a short export (Instagram keeps views
 * for weeks, but likes and messages for years) looked like Instagram use
 * across the whole range; null points are not drawn at all.
 */
export function chartRowsWithinData(
  data: FlattenedTimelineRecord[],
  datasets?: Record<string, { min_date?: string; max_date?: string; watch_min_date?: string; watch_max_date?: string }>,
): Record<string, string | number | null>[] {
  return data.map((row) => {
    const chartRow: Record<string, string | number | null> = { ...row };
    for (const [platform, hoursKey] of Object.entries(PLATFORM_HOURS_KEYS)) {
      const info = datasets?.[platform];
      // Older backends report only min/max_date (all event types).
      const minDate = info?.watch_min_date ?? info?.min_date;
      const maxDate = info?.watch_max_date ?? info?.max_date;
      if (!minDate || !maxDate || !bucketWithinData(row.date, minDate, maxDate)) {
        chartRow[hoursKey] = null;
      }
    }
    return chartRow;
  });
}

/** Spotify is simulated by the mock routes only; the live backend cannot ingest it yet. */
const COMING_SOON_PLATFORMS: string[] = usesLocalMockApi ? [] : ['spotify'];

export default function MainTimeline({
  data,
  activePlatforms,
  setActivePlatforms,
  selectedDate,
  onSelectDate,
  startDate,
  endDate,
  setDateRange,
  datasets,
  dateBounds,
  granularity = 'day',
}: MainTimelineProps) {
  const [showAdvancedFilters, setShowAdvancedFilters] = useState(false);

  const activeDateBounds = useMemo(() => {
    const readyBounds = activePlatforms
      .map((platform) => datasets?.[platform])
      .filter((dataset): dataset is { status: string; min_date: string; max_date: string } => (
        dataset?.status === 'READY' && !!dataset.min_date && !!dataset.max_date
      ));

    if (readyBounds.length === 0) {
      return dateBounds || { minDate: FALLBACK_REFERENCE_DATE, maxDate: FALLBACK_REFERENCE_DATE };
    }

    // The span of all selected platforms together (not their overlap): a
    // platform with a short history (Instagram keeps weeks) must not cut the
    // 5Y and All presets of the others down to its own start.
    const allDates = readyBounds.flatMap((dataset) => [dataset.min_date, dataset.max_date]).sort();
    return {
      minDate: allDates[0] || FALLBACK_REFERENCE_DATE,
      maxDate: allDates.at(-1) || FALLBACK_REFERENCE_DATE,
    };
  }, [activePlatforms, datasets, dateBounds]);

  const chartRows = useMemo(() => chartRowsWithinData(data, datasets), [data, datasets]);

  const referenceDate = activeDateBounds.maxDate || dateBounds?.maxDate || endDate || FALLBACK_REFERENCE_DATE;

  // Determine active preset label based on startDate
  const activePreset = useMemo(
    () => detectPreset(startDate, endDate, referenceDate, activeDateBounds.minDate),
    [activeDateBounds.minDate, endDate, referenceDate, startDate]
  );

  // Handle Preset Click
  const applyPreset = (preset: string) => {
    const { start, end } = getPresetRange(preset, referenceDate, activeDateBounds.minDate);
    setDateRange(start, end);
  };

  // Toggle individual platform
  const togglePlatform = (platform: string) => {
    const key = platform.toLowerCase();
    if (activePlatforms.includes(key)) {
      if (activePlatforms.length > 1) {
        setActivePlatforms(activePlatforms.filter(p => p !== key));
      }
    } else {
      setActivePlatforms([...activePlatforms, key]);
      const datasetInfo = datasets?.[key];
      const hasOverlap = datasetInfo?.min_date && datasetInfo?.max_date
        ? datasetInfo.min_date <= endDate && datasetInfo.max_date >= startDate
        : true;

      if (datasetInfo?.status === 'READY' && datasetInfo.min_date && datasetInfo.max_date && !hasOverlap) {
        const { start, end } = getPresetRange('30D', datasetInfo.max_date, datasetInfo.min_date);
        setDateRange(start, end);
      }
    }
  };

  const hasSelectedPlatforms = activePlatforms.length > 0;
  const hasData = data.length > 0;

  return (
    <div className="bg-white border border-brand-navy/10 rounded-3xl p-4 sm:p-6 shadow-sm space-y-6">
      {/* Controls Bar */}
      <div className="flex flex-col xl:flex-row xl:items-center xl:justify-between gap-4 pb-4 border-b border-brand-navy/5">
        <div className="flex items-center gap-3">
          <div className="w-10 h-10 rounded-xl bg-brand-navy/5 flex items-center justify-center text-brand-navy">
            <Layers className="w-5 h-5" />
          </div>
          <div>
            <h3 className="font-bold text-brand-navy text-lg">Daily Watchtime Allocation</h3>
            <p className="text-xs text-brand-navy/50">
              {granularity === 'month'
                ? 'Stacked area of average hours per day, grouped by month (long ranges).'
                : 'Stacked area representation of hours used per day.'}
            </p>
          </div>
        </div>

        <div className="flex flex-wrap items-center gap-3">
          {/* Preset Buttons Grid */}
          <div className="flex items-center bg-brand-beige/60 p-1 rounded-xl border border-brand-navy/5 flex-wrap">
            {DATE_PRESETS.map((preset) => (
              <button
                key={preset}
                onClick={() => applyPreset(preset)}
                className={`px-2.5 py-1.5 rounded-lg text-xs font-bold transition-all uppercase ${
                  activePreset === preset
                    ? 'bg-white text-brand-navy shadow-sm'
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
            className={`px-4 py-2 rounded-xl text-xs font-bold border transition-all flex items-center gap-1.5 ${
              showAdvancedFilters
                ? 'bg-brand-navy text-white border-brand-navy'
                : 'bg-white border-brand-navy/10 text-brand-navy/70 hover:border-brand-navy/20'
            }`}
          >
            <Filter className="w-3.5 h-3.5" />
            Time Filters
            {showAdvancedFilters ? <ChevronUp className="w-3.5 h-3.5" /> : <ChevronDown className="w-3.5 h-3.5" />}
          </button>

        </div>
      </div>

      {/* Advanced Custom Timeframe Expandable Section */}
      {showAdvancedFilters && (
        <div className="grid grid-cols-1 md:grid-cols-2 gap-6 bg-brand-beige/25 p-5 rounded-2xl border border-brand-navy/5 animate-slide-down text-left">
          {/* Custom Date Scope Widget */}
          <div className="space-y-2">
            <label className="text-[10px] uppercase tracking-wider font-extrabold text-brand-navy/60 flex items-center gap-1.5">
              <Calendar className="w-3.5 h-3.5 text-brand-teal" />
              Timeline Timeframe
            </label>
            <div className="flex items-center gap-2">
              <input
                type="date"
                value={startDate}
                min={activeDateBounds.minDate}
                max={activeDateBounds.maxDate}
                onChange={(e) => setDateRange(e.target.value, endDate)}
                className="bg-white border border-brand-navy/15 rounded-xl px-3 py-2 text-xs font-bold text-brand-navy focus:outline-none focus:ring-1 focus:ring-brand-teal w-full"
              />
              <span className="text-brand-navy/40 text-xs font-bold">to</span>
              <input
                type="date"
                value={endDate}
                min={activeDateBounds.minDate}
                max={activeDateBounds.maxDate}
                onChange={(e) => setDateRange(startDate, e.target.value)}
                className="bg-white border border-brand-navy/15 rounded-xl px-3 py-2 text-xs font-bold text-brand-navy focus:outline-none focus:ring-1 focus:ring-brand-teal w-full"
              />
            </div>
            <span className="text-[9px] text-brand-navy/40 block">Queries backend to update chart & matrix scope.</span>
          </div>

        </div>
      )}

      {/* Checklist Legend */}
      <div className="flex flex-wrap items-center justify-between gap-4 bg-brand-beige/30 p-4 rounded-2xl border border-brand-navy/5">
        <div className="flex flex-wrap items-center gap-3">
          {ALL_PLATFORMS.map((platform) => {
            const key = platform.toLowerCase();
            const isSupported = key === 'youtube' || key === 'instagram' || key === 'tiktok' || key === 'spotify';

            if (COMING_SOON_PLATFORMS.includes(key)) {
              return (
                <button
                  key={platform}
                  disabled={true}
                  className="flex items-center gap-2 px-3 py-1.5 rounded-lg text-xs font-bold border border-transparent bg-brand-navy/5 text-brand-navy/35 cursor-not-allowed"
                  title={`${platform} imports are not supported by the live backend yet`}
                >
                  <span
                    className="w-2.5 h-2.5 rounded-full"
                    style={{ backgroundColor: '#CBD5E1' }}
                  ></span>
                  <span>{platform}</span>
                  <span className="text-[9px] px-1.5 py-0.5 rounded bg-brand-navy/10 text-brand-navy/40 font-bold ml-1">
                    Coming soon
                  </span>
                </button>
              );
            }

            if (!isSupported) {
              return (
                <button
                  key={platform}
                  disabled={true}
                  className="flex items-center gap-2 px-3 py-1.5 rounded-lg text-xs font-bold border border-transparent bg-brand-navy/5 text-brand-navy/35 cursor-not-allowed"
                  title={`${platform} is unsupported in v5 (hosted YouTube-only demo)`}
                >
                  <span
                    className="w-2.5 h-2.5 rounded-full"
                    style={{ backgroundColor: '#CBD5E1' }}
                  ></span>
                  <span>{platform}</span>
                  <span className="text-[9px] px-1.5 py-0.5 rounded bg-brand-navy/10 text-brand-navy/40 font-bold ml-1">
                    Unsupported in v5
                  </span>
                </button>
              );
            }

            const datasetInfo = datasets?.[key] || { status: 'NOT_UPLOADED' };
            const isReady = datasetInfo.status === 'READY';
            const isProcessing = datasetInfo.status === 'PROCESSING';
            const isActive = activePlatforms.includes(key) && isReady;

            return (
              <button
                key={platform}
                disabled={!isReady}
                onClick={() => togglePlatform(platform)}
                className={`flex items-center gap-2 px-3 py-1.5 rounded-lg text-xs font-bold border transition-all ${
                  isActive
                    ? 'bg-white border-brand-navy/15 text-brand-navy shadow-sm'
                    : isReady
                    ? 'bg-transparent border-transparent text-brand-navy/40 hover:text-brand-navy/60 cursor-pointer'
                    : isProcessing
                    ? 'bg-brand-peach/10 border-brand-peach/20 text-brand-peach/80 cursor-wait'
                    : 'bg-brand-navy/5 border-transparent text-brand-navy/35 cursor-not-allowed'
                }`}
                title={
                  isProcessing
                    ? 'Extracting and normalizing dataset logs...'
                    : !isReady
                    ? 'Dataset not uploaded. Upload a ZIP file to unlock.'
                    : `Toggle ${platform}`
                }
              >
                <span
                  className={`w-2.5 h-2.5 rounded-full ${isProcessing ? 'animate-pulse' : ''}`}
                  style={{ backgroundColor: isReady || isProcessing ? PLATFORM_COLORS[key] : '#CBD5E1' }}
                ></span>
                <span>{platform}</span>
                {isReady ? (
                  isActive ? (
                    <CheckSquare className="w-3.5 h-3.5 text-brand-teal ml-1 shrink-0" />
                  ) : (
                    <Square className="w-3.5 h-3.5 text-brand-navy/25 ml-1 shrink-0" />
                  )
                ) : isProcessing ? (
                  <span className="text-[9px] px-1.5 py-0.5 rounded bg-brand-peach/20 text-brand-peach font-bold ml-1 animate-pulse">
                    Parsing
                  </span>
                ) : (
                  <span className="text-[9px] px-1.5 py-0.5 rounded bg-brand-navy/10 text-brand-navy/40 font-bold ml-1">
                    Locked
                  </span>
                )}
              </button>
            );
          })}
        </div>

        <div className="flex items-center gap-3">
          <button
            onClick={() => {
              const ready = ['youtube', 'instagram', 'tiktok', 'spotify']
                .filter((platform) => datasets?.[platform]?.status === 'READY');
              if (ready.length > 0) setActivePlatforms(ready);
            }}
            className="text-[10px] uppercase tracking-wider font-extrabold text-brand-teal hover:underline cursor-pointer"
          >
            Select All
          </button>
          <span className="text-brand-navy/25 text-xs">|</span>
          <button
            onClick={() => {
              const firstReady = ['youtube', 'instagram', 'tiktok', 'spotify']
                .find((platform) => datasets?.[platform]?.status === 'READY');
              if (firstReady) setActivePlatforms([firstReady]);
            }}
            className="text-[10px] uppercase tracking-wider font-extrabold text-brand-navy/60 hover:underline cursor-pointer"
          >
            Reset
          </button>
        </div>
      </div>

      {/* Chart Canvas */}
      <div className="h-[380px] w-full relative">
        {!hasSelectedPlatforms ? (
          <div className="absolute inset-0 flex flex-col items-center justify-center bg-brand-beige/20 border border-brand-navy/5 rounded-2xl p-6 text-center">
            <Filter className="w-10 h-10 text-brand-peach mb-3" />
            <h4 className="font-bold text-brand-navy text-sm">No Platforms Selected</h4>
            <p className="text-xs text-brand-navy/60 max-w-xs mt-1 leading-relaxed">
              Please toggle at least one social media source in the checklist filter to render the timeline analytics.
            </p>
          </div>
        ) : !hasData ? (
          <div className="absolute inset-0 flex flex-col items-center justify-center bg-brand-beige/20 border border-brand-navy/5 rounded-2xl p-6 text-center">
            <Calendar className="w-10 h-10 text-brand-navy/30 mb-3" />
            <h4 className="font-bold text-brand-navy text-sm">No Data Available</h4>
            <p className="text-xs text-brand-navy/60 max-w-xs mt-1 leading-relaxed">
              No daily watchtime records were found for the selected time horizon.
            </p>
          </div>
        ) : (
          <ResponsiveContainer width="100%" height="100%">
            <AreaChart
              data={chartRows}
              margin={{ top: 10, right: 10, left: -20, bottom: 0 }}
              onClick={(state) => {
                if (state && state.activeLabel !== undefined && state.activeLabel !== null) {
                  onSelectDate(String(state.activeLabel));
                }
              }}
              className="cursor-pointer"
            >
              <CartesianGrid strokeDasharray="3 3" stroke="#537D96" strokeOpacity={0.07} />
              <XAxis
                dataKey="date"
                // Calendar labels without timezone shifts (YYYY-MM-DD / YYYY-MM buckets).
                tickFormatter={(value) => formatAxisLabel(String(value), data.length)}
                tick={{ fill: '#537D96', fontSize: 10, fontWeight: 600 }}
                axisLine={{ stroke: '#537D96', strokeOpacity: 0.15 }}
                tickLine={false}
              />
              <YAxis
                tickFormatter={(val) => `${val}h`}
                tick={{ fill: '#537D96', fontSize: 10, fontWeight: 600 }}
                axisLine={{ stroke: '#537D96', strokeOpacity: 0.15 }}
                tickLine={false}
              />
              <Tooltip
                contentStyle={{
                  backgroundColor: '#FFFFFF',
                  borderRadius: '16px',
                  border: '1px solid rgba(83, 125, 150, 0.15)',
                  boxShadow: '0 4px 12px rgba(0,0,0,0.05)',
                  fontFamily: 'Outfit, sans-serif',
                }}
                labelClassName="font-extrabold text-brand-navy text-xs mb-2 block border-b border-brand-navy/5 pb-1"
                labelFormatter={(label) => {
                  const value = String(label);
                  return isYearMonth(value)
                    ? `${formatCalendarValue(value, { month: 'long', year: 'numeric' })} (avg per day)`
                    : formatCalendarValue(value, { weekday: 'short', month: 'short', day: 'numeric', year: 'numeric' });
                }}
                formatter={(value: any, name: any) => {
                  if (value === null || value === undefined) return null;
                  const unit = granularity === 'month' ? 'hrs/day' : 'hrs';
                  if (PLATFORM_LABELS[name]) {
                    return [`${value} ${unit}`, PLATFORM_LABELS[name]];
                  }
                  return [`${value} ${unit}`, name];
                }}
              />

              {/* Stacked Areas in hours */}
              {activePlatforms.includes('youtube') && (
                <Area
                  type="monotone"
                  dataKey="youtubeHours"
                  stackId="1"
                  stroke="#537D96"
                  fill="#537D96"
                  fillOpacity={0.75}
                />
              )}
              {activePlatforms.includes('instagram') && (
                <Area
                  type="monotone"
                  dataKey="instagramHours"
                  stackId="1"
                  stroke="#EC8F8D"
                  fill="#EC8F8D"
                  fillOpacity={0.75}
                />
              )}
              {activePlatforms.includes('tiktok') && (
                <Area
                  type="monotone"
                  dataKey="tiktokHours"
                  stackId="1"
                  stroke="#44A194"
                  fill="#44A194"
                  fillOpacity={0.75}
                />
              )}
              {activePlatforms.includes('spotify') && (
                <Area
                  type="monotone"
                  dataKey="spotifyHours"
                  stackId="1"
                  stroke="#5EAF81"
                  fill="#5EAF81"
                  fillOpacity={0.75}
                />
              )}
              {activePlatforms.includes('twitter') && (
                <Area
                  type="monotone"
                  dataKey="twitterHours"
                  stackId="1"
                  stroke="#8ba6b8"
                  fill="#8ba6b8"
                  fillOpacity={0.75}
                />
              )}
              {activePlatforms.includes('linkedin') && (
                <Area
                  type="monotone"
                  dataKey="linkedinHours"
                  stackId="1"
                  stroke="#66b8ad"
                  fill="#66b8ad"
                  fillOpacity={0.75}
                />
              )}

            </AreaChart>
          </ResponsiveContainer>
        )}
      </div>

      {/* Helper Legend explanation */}
      <div className="flex items-center justify-between text-xs text-brand-navy/60 font-semibold px-2">
        <div className="flex items-center gap-4">
          <div className="flex items-center gap-1.5">
            <span className="w-3.5 h-3.5 bg-brand-teal/80 border border-brand-teal/40 rounded"></span>
            <span>Stacked Platform Allocations</span>
          </div>
        </div>
        {selectedDate && (
          <div className="text-brand-teal font-extrabold">
            Selected {isYearMonth(selectedDate) ? 'Month' : 'Date'}:{' '}
            {isYearMonth(selectedDate) ? formatCalendarValue(selectedDate, { month: 'long', year: 'numeric' }) : selectedDate}
          </div>
        )}
      </div>
    </div>
  );
}
