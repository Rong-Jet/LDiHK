import React, { useEffect, useMemo, useState } from 'react';
import { QueryClientProvider } from '@tanstack/react-query';
import {
  RefreshCw, Users, Database, ShieldAlert,
  TrendingUp, Activity, Calendar, Filter, Layers, CheckSquare, Square,
  ChevronDown, ChevronUp, Clock, Info
} from 'lucide-react';
import {
  AreaChart, Area, XAxis, YAxis, Tooltip, ResponsiveContainer,
  ReferenceLine, ComposedChart, Line, Legend, CartesianGrid,
  BarChart, Bar, Cell
} from 'recharts';
import ConsoleShell from './ConsoleShell';
import { ProfileCard } from './ProfileCard';
import { COMPARABLE_PLATFORMS, describeComparisonGroup, hasProfile, platformList } from '../lib/profile';
import type { PopulationSource } from '../lib/api';
import { usePopulationData } from '../hooks/usePopulationData';
import { useBackendStatus } from '../hooks/useBackendStatus';
import { useConsoleSession } from '../hooks/useConsoleSession';
import { describeApiError, usesLocalMockApi } from '../lib/api';
import {
  DATE_PRESETS,
  defaultRangeForBounds,
  detectPreset,
  getPresetRange,
  type DateBounds,
} from '../lib/dates';
import { createConsoleQueryClient } from '../lib/queryClient';

const IS_MOCK_MODE = usesLocalMockApi;

const ALL_PLATFORMS = ['YouTube', 'Instagram', 'TikTok', 'Spotify', 'Twitter', 'LinkedIn'];

const PLATFORM_COLORS: Record<string, string> = {
  youtube: '#537D96',   // brand-navy
  instagram: '#EC8F8D', // brand-peach
  tiktok: '#44A194',    // brand-teal
  spotify: '#5EAF81',   // brand-green
  twitter: '#8ba6b8',
  linkedin: '#66b8ad',
};

// The backend population benchmark compares YouTube watch time only.
const LIVE_POPULATION_PLATFORMS = COMPARABLE_PLATFORMS;
const MOCK_POPULATION_PLATFORMS = ['youtube', 'instagram', 'tiktok', 'spotify'];

function PopulationDashboardContent() {
  const backend = useBackendStatus();
  const session = useConsoleSession({ backendReady: backend.isReady });
  const { sessionToken, datasets } = session;

  const [includeSynthetic, setIncludeSynthetic] = useState(true);
  // Compare with people of similar age and sex when the user gave either.
  const [compareEveryone, setCompareEveryone] = useState(false);
  const compareWith = hasProfile(session.profile) && !compareEveryone ? 'cohort' : 'everyone';
  // Selected platforms vs. the population's total social media time (default).
  const [populationSource, setPopulationSource] = useState<PopulationSource>('total');

  // Custom Percentile Line parameters
  const [showCustomPercentile, setShowCustomPercentile] = useState(false);
  const [customPercentile, setCustomPercentile] = useState(90);

  // Timeframe filters; empty until /api/me delivered the real date bounds.
  const [startDate, setStartDate] = useState('');
  const [endDate, setEndDate] = useState('');
  const [showAdvancedFilters, setShowAdvancedFilters] = useState(false);
  const [activePlatforms, setActivePlatforms] = useState<string[]>(['youtube']);

  // Platforms the population benchmark can compare for this user.
  const readyPlatforms = useMemo(() => {
    const supported = IS_MOCK_MODE ? MOCK_POPULATION_PLATFORMS : LIVE_POPULATION_PLATFORMS;
    return supported.filter((platform) => session.readyPlatforms.includes(platform));
  }, [session.readyPlatforms]);

  // Bounds of the comparable platforms (population days are UTC calendar days).
  const discoveredBounds = useMemo<DateBounds | null>(() => {
    const summaries = readyPlatforms
      .map((platform) => datasets[platform])
      .filter((summary) => summary?.min_date && summary?.max_date);
    if (summaries.length === 0) return null;
    return {
      minDate: summaries.map((summary) => summary!.min_date as string).sort()[0],
      maxDate: summaries.map((summary) => summary!.max_date as string).sort().slice(-1)[0],
    };
  }, [readyPlatforms, datasets]);

  // A different LDiHK-ID starts from a clean view.
  useEffect(() => {
    setStartDate('');
    setEndDate('');
    setActivePlatforms(['youtube']);
  }, [sessionToken]);

  const boundsKey = discoveredBounds ? `${discoveredBounds.minDate}|${discoveredBounds.maxDate}` : '';
  useEffect(() => {
    if (!discoveredBounds) return;
    const { start, end } = defaultRangeForBounds(discoveredBounds);
    setStartDate(start);
    setEndDate(end);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [boundsKey]);

  const queryPlatforms = activePlatforms.filter((platform) => readyPlatforms.includes(platform));

  // Fetch Population Analytics (straight from the backend in live mode)
  const {
    data: popData,
    isLoading: isPopLoading,
    error: popError,
    refetch: refetchPop
  } = usePopulationData(
    queryPlatforms,
    startDate,
    endDate,
    includeSynthetic,
    customPercentile,
    backend.isReady && queryPlatforms.length > 0,
    sessionToken,
    startDate,
    compareWith,
    IS_MOCK_MODE ? 'matching' : populationSource
  );

  const handleResetView = () => {
    setShowAdvancedFilters(false);
    setCustomPercentile(90);
    setShowCustomPercentile(false);
    setActivePlatforms(['youtube']);
    if (discoveredBounds) {
      const { start, end } = defaultRangeForBounds(discoveredBounds);
      setStartDate(start);
      setEndDate(end);
    }
  };

  // Active preset matching MainTimeline
  const referenceDate = discoveredBounds?.maxDate ?? endDate;
  const activePreset = useMemo(
    () => detectPreset(startDate, endDate, referenceDate, discoveredBounds?.minDate),
    [startDate, endDate, referenceDate, discoveredBounds?.minDate]
  );

  const applyPreset = (preset: string) => {
    if (!referenceDate) return;
    const { start, end } = getPresetRange(preset, referenceDate, discoveredBounds?.minDate);
    setStartDate(start);
    setEndDate(end);
  };

  const togglePlatform = (platform: string) => {
    const key = platform.toLowerCase();
    if (activePlatforms.includes(key)) {
      if (activePlatforms.length > 1) {
        setActivePlatforms(activePlatforms.filter(p => p !== key));
      }
    } else {
      setActivePlatforms([...activePlatforms, key]);
    }
  };

  const visibleDeciles = useMemo(() => {
    if (!popData?.deciles) return [];
    return popData.deciles.filter(record => record.date >= startDate && record.date <= endDate);
  }, [popData?.deciles, startDate, endDate]);

  // Group distribution data into 1-hour interval bins (0-24h)
  const binData = useMemo(() => {
    if (!popData?.distribution) return [];

    // Initialize 24 bins representing 0-24h
    const bins = Array.from({ length: 24 }, (_, i) => {
      const min = i;
      const max = i + 1;
      return {
        min,
        max,
        density: 0,
        isUserBin: false,
      };
    });

    // Sum density into corresponding bins
    popData.distribution.forEach((item) => {
      const hr = item.hours;
      const binIdx = Math.min(23, Math.floor(hr));
      if (binIdx >= 0) {
        bins[binIdx].density += item.density;
      }
    });

    // Identify user's bin
    const userAvg = popData.userDailyAverageHours;
    const userBinIdx = userAvg === null ? -1 : Math.min(23, Math.floor(userAvg));
    if (userBinIdx >= 0 && userBinIdx < 24) {
      bins[userBinIdx].isUserBin = true;
    }

    // Calculate total density to compute percentage distribution
    const totalDensity = bins.reduce((sum, b) => sum + b.density, 0);

    // Calculate percentage (so that the bars add up to 100%) and build range labels
    return bins.map(b => {
      const percentage = totalDensity > 0 ? parseFloat(((b.density / totalDensity) * 100).toFixed(1)) : 0;
      return {
        ...b,
        percentage,
        range: b.isUserBin ? `${b.min}-${b.max}h (You)` : `${b.min}-${b.max}h`
      };
    });
  }, [popData]);

  // 6. Generate dynamic copy and badges based on user's consumption percentile for health-oriented insights
  const percentileNuance = useMemo(() => {
    if (!popData) return null;
    const p = popData.userPercentile;
    if (p === null) return null;

    if (p >= 75) {
      return {
        title: <>Your daily usage exceeds <span className="text-brand-peach">{p}%</span> of the population</>,
        status: "High Consumption Bracket",
        description: "Your watch time falls into the upper quartile. High media consumption can impact focus, sleep quality, and overall digital well-being. Consider setting mindful downtime goals."
      };
    } else if (p >= 40) {
      return {
        title: <>Your daily usage exceeds <span className="text-brand-teal">{p}%</span> of the population</>,
        status: "Moderate Consumption Bracket",
        description: "Your watch time aligns with the general population median. Regular screen breaks and active check-ins can help you maintain this balanced baseline."
      };
    } else {
      const inversePct = 100 - p;
      return {
        title: <>Your daily usage is lower than <span className="text-brand-teal">{inversePct}%</span> of the population</>,
        status: "Balanced Consumption Bracket",
        description: "Your watch time is below the population average. Lower screen time provides cognitive rest, supports better sleep hygiene, and encourages physical presence."
      };
    }
  }, [popData]);

  const hasSelectedPlatforms = activePlatforms.some(p => readyPlatforms.includes(p));

  // In production mode the backend may not yet serve population comparison data;
  // hasPopulationData tracks whether we received real comparative metrics.
  const hasPopulationData = popData?.hasPopulationData === true;
  const tooFewPeople = popData?.reason === 'insufficient_population';
  const unavailableMessage =
    popData?.message ??
    'There is no YouTube watch history in the selected date range. Choose a range with data, or upload a YouTube Takeout export.';
  const groupLabel = describeComparisonGroup(popData?.comparisonGroup);
  const sourceNote = popData && !IS_MOCK_MODE
    ? ` Your ${platformList(queryPlatforms)} time is compared with ${
        popData.populationSource === 'total' ? 'their total social media time' : `their ${platformList(popData.comparisonPlatforms)} time`
      }.`
    : '';
  const comparisonNote = popData?.populationSize
    ? (groupLabel ? ` Compared with ${groupLabel}` : ` Compared with ${popData.populationSize.toLocaleString()} other ${popData.populationSize === 1 ? 'person' : 'people'}`) +
      (popData.includeSynthetic && popData.syntheticBaseline
        ? ` (synthetic profiles act as a weekday baseline from ${popData.syntheticBaseline.startDate} to ${popData.syntheticBaseline.endDate}).`
        : '.') + sourceNote
    : '';

  const content = (
      <div className="space-y-6 text-left">
        {sessionToken && (
          <ProfileCard
            profile={session.profile}
            onSave={session.saveProfile}
            comparisonGroup={popData?.comparisonGroup}
          />
        )}
        {readyPlatforms.length === 0 && (
          <div className="bg-brand-teal/10 border border-brand-teal/25 rounded-2xl px-4 py-3 text-brand-navy text-xs leading-relaxed flex gap-2 items-center">
            <Info className="w-4 h-4 text-brand-teal shrink-0" />
            The population benchmark compares YouTube watch history. Upload a YouTube Takeout export to see where you stand.
          </div>
        )}
        {/* Top Banner KPI Card */}
        <div className="bg-gradient-to-r from-brand-navy to-brand-navy/90 text-white rounded-[32px] p-6 sm:p-8 relative overflow-hidden shadow-lg border border-brand-navy/25">
          <div className="absolute right-0 bottom-0 w-64 h-64 bg-brand-teal/20 rounded-full blur-3xl pointer-events-none"></div>
          <div className="absolute left-1/3 top-0 w-48 h-48 bg-brand-peach/15 rounded-full blur-2xl pointer-events-none"></div>

          <div className="relative z-10 flex flex-col md:flex-row md:items-center justify-between gap-6">
            <div className="space-y-2 flex-grow">
              <div className="inline-flex items-center gap-2 px-3 py-1 rounded-full bg-white/10 border border-white/15 text-[10px] font-extrabold uppercase tracking-wider">
                <Users className="w-3.5 h-3.5 text-brand-teal" />
                Population Placement Analysis
              </div>
              {isPopLoading ? (
                <h2 className="text-2xl sm:text-3xl font-black tracking-tight leading-tight animate-pulse">Calculating Standings...</h2>
              ) : popData && hasPopulationData && percentileNuance ? (
                <>
                  <h2 className="text-2xl sm:text-3xl font-black tracking-tight leading-tight">
                    {percentileNuance.title}
                  </h2>
                  <div className="inline-block px-2.5 py-0.5 text-[9px] font-extrabold uppercase tracking-wider rounded-md border border-white/20 bg-white/5 mt-1.5">
                    {percentileNuance.status}{IS_MOCK_MODE ? ' · Simulated' : ' · Population Comparison Active'}
                  </div>
                </>
              ) : popData && !hasPopulationData ? (
                <h2 className="text-2xl sm:text-3xl font-black tracking-tight leading-tight">
                  {tooFewPeople ? 'Not enough people to compare with yet' : 'Nothing to compare in this range yet'}
                </h2>
              ) : null}
              <p className="text-xs text-white/70 max-w-xl leading-relaxed pt-1">
                {popData && !hasPopulationData
                  ? unavailableMessage
                  : percentileNuance
                  ? `${percentileNuance.description} Days and hours are compared in UTC so every user is measured on the same clock.${comparisonNote}`
                  : ""}
              </p>
            </div>
          </div>
        </div>

        {/* Parameters Row: Synthetic toggle */}
        <div className="bg-white p-4 rounded-3xl border border-brand-navy/10 shadow-sm flex flex-col sm:flex-row items-start sm:items-center justify-between gap-4">
          <div>
            <h3 className="font-extrabold text-brand-navy text-xs uppercase tracking-wider">Workspace Database Settings</h3>
            <p className="text-[10px] text-brand-navy/50">Modify the data source context for comparison statistics.</p>
          </div>

          <div className="flex flex-col sm:flex-row gap-3 w-full sm:w-auto">
          {hasProfile(session.profile) && (
            <div className="flex items-center gap-3 bg-brand-beige/20 border border-brand-navy/10 rounded-2xl p-2.5 px-4 select-none w-full sm:w-auto justify-between">
              <div>
                <span className="text-xs font-black text-brand-navy block">Compare With My Age &amp; Sex</span>
                <span className="text-[9px] text-brand-navy/50 block -mt-0.5">Off: compare with everyone</span>
              </div>
              <button
                onClick={() => setCompareEveryone(!compareEveryone)}
                className={`relative inline-flex h-6 w-11 shrink-0 rounded-full border-2 border-transparent transition-colors duration-200 ease-in-out focus:outline-none ${
                  !compareEveryone ? 'bg-brand-teal' : 'bg-brand-navy/20'
                } cursor-pointer`}
                role="switch"
                aria-checked={!compareEveryone}
                id="toggle-compare-cohort"
                title="Compare with people of similar age and sex"
              >
                <span
                  aria-hidden="true"
                  className={`pointer-events-none inline-block h-5 w-5 transform rounded-full bg-white shadow ring-0 transition duration-200 ease-in-out ${
                    !compareEveryone ? 'translate-x-5' : 'translate-x-0'
                  }`}
                />
              </button>
            </div>
          )}
          <div className="flex items-center gap-3 bg-brand-beige/20 border border-brand-navy/10 rounded-2xl p-2.5 px-4 select-none w-full sm:w-auto justify-between">
            <div>
              <span className="text-xs font-black text-brand-navy block">Synthetic Population Data</span>
              <span className="text-[9px] text-brand-navy/50 block -mt-0.5">Use large realistic curves vs small local dataset</span>
            </div>
            <button
              onClick={() => setIncludeSynthetic(!includeSynthetic)}
              className={`relative inline-flex h-6 w-11 shrink-0 rounded-full border-2 border-transparent transition-colors duration-200 ease-in-out focus:outline-none ${
                includeSynthetic ? 'bg-brand-teal' : 'bg-brand-navy/20'
              } cursor-pointer`}
              role="switch"
              aria-checked={includeSynthetic}
              id="toggle-synthetic-data"
              title="Toggle Synthetic Population Data"
            >
              <span
                aria-hidden="true"
                className={`pointer-events-none inline-block h-5 w-5 transform rounded-full bg-white shadow ring-0 transition duration-200 ease-in-out ${
                  includeSynthetic ? 'translate-x-5' : 'translate-x-0'
                }`}
              />
            </button>
          </div>
          </div>
        </div>

        {/* Timeline and Bell Curve Section */}
        {popError ? (
          <div className="bg-brand-peach/10 border border-brand-peach/30 rounded-3xl p-8 text-center text-brand-navy flex flex-col items-center gap-3">
            <ShieldAlert className="w-10 h-10 text-brand-peach" />
            <h4 className="font-bold">Failed to load comparative statistics</h4>
            <p className="text-xs text-brand-navy/70">{describeApiError(popError)}</p>
            <button
              onClick={() => refetchPop()}
              className="px-4 py-2 rounded-xl bg-brand-navy text-white text-xs font-bold cursor-pointer"
            >
              Retry Request
            </button>
          </div>
        ) : (
          <div className="grid grid-cols-1 xl:grid-cols-3 gap-6">

            {/* Timeline Chart (2/3 width on xl) */}
            <div className="xl:col-span-2">
              <div className="bg-white border border-brand-navy/10 rounded-3xl p-4 sm:p-6 shadow-sm space-y-6">

                {/* Timeline Header Row (emulating MainTimeline controls) */}
                <div className="flex flex-col xl:flex-row xl:items-center xl:justify-between gap-4 pb-4 border-b border-brand-navy/5">
                  <div className="flex items-center gap-3">
                    <div className="w-10 h-10 rounded-xl bg-brand-navy/5 flex items-center justify-center text-brand-navy">
                      <Layers className="w-5 h-5" />
                    </div>
                    <div>
                      <div className="flex items-center gap-2">
                        <h3 className="font-bold text-brand-navy text-lg">Population Cohort Timeline</h3>
                      </div>
                      <p className="text-xs text-brand-navy/50">Your daily hours compared to Median and Top 10% ranges.</p>
                    </div>
                  </div>

                  <div className="flex flex-wrap items-center gap-3">
                    {/* Presets */}
                    <div className="flex items-center bg-brand-beige/60 p-1 rounded-xl border border-brand-navy/5 flex-wrap">
                      {DATE_PRESETS.map((preset) => (
                        <button
                          key={preset}
                          onClick={() => applyPreset(preset)}
                          className={`px-2.5 py-1.5 rounded-lg text-xs font-bold transition-all uppercase cursor-pointer ${
                            activePreset === preset
                              ? 'bg-white text-brand-navy shadow-sm'
                              : 'text-brand-navy/60 hover:text-brand-navy'
                          }`}
                        >
                          {preset === 'all' ? 'All' : preset}
                        </button>
                      ))}
                    </div>

                    {/* Advanced Options Toggle */}
                    <button
                      onClick={() => setShowAdvancedFilters(!showAdvancedFilters)}
                      className={`px-4 py-2 rounded-xl text-xs font-bold border transition-all flex items-center gap-1.5 cursor-pointer ${
                        showAdvancedFilters
                          ? 'bg-brand-navy text-white border-brand-navy'
                          : 'bg-white border-brand-navy/10 text-brand-navy/70 hover:border-brand-navy/20'
                      }`}
                    >
                      <Filter className="w-3.5 h-3.5" />
                      Options
                      {showAdvancedFilters ? <ChevronUp className="w-3.5 h-3.5" /> : <ChevronDown className="w-3.5 h-3.5" />}
                    </button>

                  </div>
                </div>

                {/* Advanced Options Drawer */}
                {showAdvancedFilters && (
                  <div className="grid grid-cols-1 sm:grid-cols-2 gap-6 bg-brand-beige/25 p-5 rounded-2xl border border-brand-navy/5 animate-slide-down">
                    {/* 1. Date Range picker */}
                    <div className="space-y-2 sm:col-span-2">
                      <label className="text-[10px] uppercase tracking-wider font-extrabold text-brand-navy/60 flex items-center gap-1.5">
                        <Calendar className="w-3.5 h-3.5 text-brand-teal" />
                        Custom Timeframe
                      </label>
                      <div className="flex items-center gap-2">
                        <input
                          type="date"
                          value={startDate}
                          min={discoveredBounds?.minDate}
                          max={discoveredBounds?.maxDate}
                          onChange={(e) => setStartDate(e.target.value)}
                          className="bg-white border border-brand-navy/15 rounded-xl px-3 py-2 text-xs font-bold text-brand-navy focus:outline-none focus:ring-1 focus:ring-brand-teal w-full"
                        />
                        <span className="text-brand-navy/40 text-xs font-bold">to</span>
                        <input
                          type="date"
                          value={endDate}
                          min={discoveredBounds?.minDate}
                          max={discoveredBounds?.maxDate}
                          onChange={(e) => setEndDate(e.target.value)}
                          className="bg-white border border-brand-navy/15 rounded-xl px-3 py-2 text-xs font-bold text-brand-navy focus:outline-none focus:ring-1 focus:ring-brand-teal w-full"
                        />
                      </div>
                    </div>

                    {/* 2. Custom Percentile Line Controls */}
                    {hasPopulationData && (
                      <div className="space-y-2">
                        <label className="text-[10px] uppercase tracking-wider font-extrabold text-brand-navy/60 flex items-center gap-1.5 justify-between">
                          <span className="flex items-center gap-1.5">
                            <span className="w-2.5 h-2.5 rounded-full bg-brand-teal"></span>
                            Custom Percentile Line
                          </span>
                          <input
                            type="checkbox"
                            checked={showCustomPercentile}
                            onChange={(e) => setShowCustomPercentile(e.target.checked)}
                            className="rounded text-brand-teal focus:ring-brand-teal h-3.5 w-3.5 cursor-pointer"
                            id="checkbox-show-percentile"
                          />
                        </label>
                        <div className="flex items-center gap-3">
                          <input
                            type="range"
                            min="1"
                            max="99"
                            disabled={!showCustomPercentile}
                            value={customPercentile}
                            onChange={(e) => setCustomPercentile(parseInt(e.target.value))}
                            className="w-full h-1.5 bg-brand-navy/10 rounded-lg appearance-none cursor-pointer accent-brand-teal disabled:opacity-40"
                          />
                          <span className="text-xs font-black text-brand-navy w-8 text-right">
                            {customPercentile}%
                          </span>
                        </div>
                      </div>
                    )}

                    {!IS_MOCK_MODE && (
                      <div className="space-y-2 sm:col-span-2">
                        <label htmlFor="population-source" className="text-[10px] uppercase tracking-wider font-extrabold text-brand-navy/60 flex items-center gap-1.5">
                          <Users className="w-3.5 h-3.5 text-brand-teal" />
                          Compare With The Population's
                        </label>
                        <select
                          id="population-source"
                          value={populationSource}
                          onChange={(event) => setPopulationSource(event.target.value as PopulationSource)}
                          className="w-full sm:w-auto bg-white border border-brand-navy/20 rounded-xl px-3 py-2 text-xs font-semibold text-brand-navy focus:outline-none focus:ring-2 focus:ring-brand-teal/30"
                        >
                          <option value="total">Total social media time (YouTube, TikTok, Instagram, LinkedIn)</option>
                          <option value="matching">Time on the same platforms as mine ({platformList(queryPlatforms)})</option>
                        </select>
                      </div>
                    )}
                  </div>
                )}

                {/* Platform Checklist Legend (emulating MainTimeline's selection checklist) */}
                <div className="flex flex-wrap items-center justify-between gap-4 bg-brand-beige/30 p-4 rounded-2xl border border-brand-navy/5">
                  <div className="flex flex-wrap items-center gap-3">
                    {ALL_PLATFORMS.map((platform) => {
                      const key = platform.toLowerCase();
                      const isSupported = key === 'youtube' || key === 'instagram' || key === 'tiktok' || key === 'spotify';

                      if (!isSupported) {
                        return (
                          <button
                            key={platform}
                            disabled={true}
                            className="flex items-center gap-2 px-3 py-1.5 rounded-lg text-xs font-bold border border-transparent bg-brand-navy/5 text-brand-navy/35 cursor-not-allowed"
                            title={`${platform} is unsupported in this version`}
                          >
                            <span
                              className="w-2.5 h-2.5 rounded-full"
                              style={{ backgroundColor: '#CBD5E1' }}
                            ></span>
                            <span>{platform}</span>
                            <span className="text-[9px] px-1.5 py-0.5 rounded bg-brand-navy/10 text-brand-navy/40 font-bold ml-1">
                              Locked
                            </span>
                          </button>
                        );
                      }

                      const datasetInfo = { status: readyPlatforms.includes(key) ? 'READY' : 'NOT_UPLOADED' };
                      const isReady = datasetInfo.status === 'READY';
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
                              : 'bg-brand-navy/5 border-transparent text-brand-navy/35 cursor-not-allowed'
                          }`}
                        >
                          <span
                            className="w-2.5 h-2.5 rounded-full"
                            style={{ backgroundColor: isReady ? PLATFORM_COLORS[key] : '#CBD5E1' }}
                          ></span>
                          <span>{platform}</span>
                          {isReady ? (
                            isActive ? (
                              <CheckSquare className="w-3.5 h-3.5 text-brand-teal ml-1 shrink-0" />
                            ) : (
                              <Square className="w-3.5 h-3.5 text-brand-navy/25 ml-1 shrink-0" />
                            )
                          ) : (
                            <span className="text-[9px] px-1.5 py-0.5 rounded bg-brand-navy/10 text-brand-navy/40 font-bold ml-1">
                              Locked
                            </span>
                          )}
                        </button>
                      );
                    })}
                  </div>
                </div>

                {/* Chart Canvas */}
                <div className="h-[360px] w-full relative">
                  {!hasSelectedPlatforms ? (
                    <div className="absolute inset-0 flex flex-col items-center justify-center bg-brand-beige/20 border border-brand-navy/5 rounded-2xl p-6 text-center">
                      <Filter className="w-10 h-10 text-brand-peach mb-3" />
                      <h4 className="font-bold text-brand-navy text-sm">No Platforms Selected</h4>
                      <p className="text-xs text-brand-navy/60 max-w-xs mt-1 leading-relaxed">
                        Please toggle at least one social media source in the checklist filter to display the population comparison timeline.
                      </p>
                    </div>
                  ) : isPopLoading || !popData ? (
                    <div className="absolute inset-0 flex items-center justify-center">
                      <RefreshCw className="w-8 h-8 animate-spin text-brand-teal" />
                    </div>
                  ) : (
                    <ResponsiveContainer width="100%" height="100%">
                      <ComposedChart
                        data={visibleDeciles}
                        margin={{ top: 10, right: 15, left: -20, bottom: 0 }}
                      >
                        <CartesianGrid strokeDasharray="3 3" stroke="#537D96" strokeOpacity={0.07} />
                        <XAxis
                          dataKey="date"
                          tickFormatter={(str) => {
                            const parts = str.split('-');
                            if (parts.length === 3) {
                              const dateObj = new Date(str);
                              const diffDays = visibleDeciles.length;
                              if (diffDays > 730) return dateObj.toLocaleDateString('en-US', { year: 'numeric' });
                              if (diffDays > 30) return dateObj.toLocaleDateString('en-US', { month: 'short', year: '2-digit' });
                              return `${parts[1]}/${parts[2]}`;
                            }
                            return str;
                          }}
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
                          formatter={(value: any, name: any): any => {
                            if (value === null || value === undefined) return null;
                            if (name === 'user') return [`${value} hrs`, 'Your Watch Hours'];
                            if (name === 'median') return [`${value} hrs`, 'Population Median (50th)'];
                            if (name === 'top10') return [`${value} hrs`, 'Top 10% Power Users'];
                            if (name === 'bottom10') return [`${value} hrs`, 'Bottom 10% Users'];
                            if (name === 'customPercentileHours') return [`${value} hrs`, `Custom ${customPercentile}th Percentile`];
                            return [`${value} hrs`, name];
                          }}
                        />

                        {/* Shaded Areas representing Cohort Bands */}
                        {hasPopulationData && (
                          <>
                            <Area
                              name="top10"
                              type="monotone"
                              dataKey="top10"
                              fill="#44A194"
                              fillOpacity={0.06}
                              stroke="none"
                            />
                            <Area
                              name="median"
                              type="monotone"
                              dataKey="median"
                              fill="#537D96"
                              fillOpacity={0.09}
                              stroke="none"
                            />
                          </>
                        )}

                        {/* Solid line representing User Watch hours */}
                        <Line
                          name="user"
                          type="monotone"
                          dataKey="user"
                          stroke="#EC8F8D"
                          strokeWidth={3}
                          dot={false}
                          activeDot={{ r: 6, stroke: '#FFFFFF', strokeWidth: 2 }}
                        />

                        {/* Dashed line representing custom percentile if toggled */}
                        {hasPopulationData && showCustomPercentile && (
                          <Line
                            name="customPercentileHours"
                            type="monotone"
                            dataKey="customPercentileHours"
                            stroke="#44A194"
                            strokeWidth={2}
                            strokeDasharray="4 4"
                            dot={false}
                            activeDot={false}
                          />
                        )}
                      </ComposedChart>
                    </ResponsiveContainer>
                  )}
                </div>

                {/* Legend explanation footer */}
                <div className="flex flex-wrap items-center justify-between text-xs text-brand-navy/60 font-semibold px-2 gap-4">
                  <div className="flex flex-wrap items-center gap-4">
                    <div className="flex items-center gap-1.5">
                      <span className="w-3.5 h-3.5 bg-brand-peach rounded"></span>
                      <span>Your Watch Time</span>
                    </div>
                    {hasPopulationData && (
                      <div className="flex items-center gap-1.5">
                        <span className="w-3.5 h-3.5 bg-brand-navy/15 rounded"></span>
                        <span>Median Cohort Shading</span>
                      </div>
                    )}
                    {hasPopulationData && showCustomPercentile && (
                      <div className="flex items-center gap-1.5">
                        <span className="w-3.5 h-1 border-t-2 border-dashed border-brand-teal"></span>
                        <span>{customPercentile}th Percentile Benchmark</span>
                      </div>
                    )}
                  </div>
                </div>

              </div>
            </div>

            {/* Watch Time Distribution (1/3 width on xl) */}
            <div className="bg-white p-6 rounded-3xl border border-brand-navy/10 shadow-sm flex flex-col justify-between">
              <div>
                <h3 className="font-extrabold text-brand-navy text-sm uppercase tracking-wider flex items-center gap-2 mb-2">
                  <TrendingUp className="w-4 h-4 text-brand-teal" />
                  Watch Time Distribution
                </h3>
                <p className="text-xs text-brand-navy/60 leading-relaxed mb-6">
                  A horizontal bar chart showing user distribution in 1-hour cohorts. Your position is highlighted in peach.
                </p>
              </div>

              <div className="h-[480px] w-full flex items-center justify-center">
                {popData && !hasPopulationData ? (
                  <div className="text-center p-6 space-y-3 max-w-xs bg-brand-beige/10 rounded-2xl border border-brand-navy/5">
                    <TrendingUp className="w-8 h-8 text-brand-navy/40 mx-auto" />
                    <p className="text-xs font-bold text-brand-navy">Population distribution unavailable</p>
                    <p className="text-[10px] text-brand-navy/50 leading-relaxed">{unavailableMessage}</p>
                  </div>
                ) : isPopLoading || !popData ? (
                  <div className="h-full flex items-center justify-center">
                    <RefreshCw className="w-6 h-6 animate-spin text-brand-teal" />
                  </div>
                ) : (
                  <ResponsiveContainer width="100%" height="100%">
                    <BarChart
                      layout="vertical"
                      data={binData}
                      margin={{ top: 5, right: 15, left: -15, bottom: 5 }}
                    >
                      <CartesianGrid strokeDasharray="3 3" stroke="#537D96" strokeOpacity={0.07} />
                      <XAxis
                        type="number"
                        stroke="#537D96"
                        fontSize={9}
                        fontWeight="bold"
                        tickLine={false}
                        axisLine={false}
                        tickFormatter={(val) => `${val}%`}
                        label={{ value: 'Percentage of Cohort (%)', position: 'insideBottom', offset: -5, fontSize: 9, fill: '#537D96', fontWeight: 'bold' }}
                      />
                      <YAxis
                        dataKey="range"
                        type="category"
                        stroke="#537D96"
                        fontSize={9}
                        fontWeight="bold"
                        tickLine={false}
                        axisLine={false}
                        width={75}
                      />
                      <Tooltip
                        content={({ active, payload }) => {
                          if (active && payload && payload.length) {
                            const data = payload[0].payload;
                            return (
                              <div className="bg-white p-3 rounded-2xl shadow-lg border border-brand-navy/15 text-xs font-semibold text-brand-navy space-y-1.5 min-w-[155px]">
                                <p className="font-extrabold border-b border-brand-navy/5 pb-1 text-brand-navy">{data.range}</p>
                                <p className="flex justify-between gap-4">
                                  <span>Cohort Ratio:</span>
                                  <span className="font-mono font-bold text-brand-teal">
                                    {data.percentage}%
                                  </span>
                                </p>
                                <p className="flex justify-between gap-4 text-brand-navy/60 text-[10px]">
                                  <span>User Count:</span>
                                  <span className="font-mono">
                                    {popData.includeSynthetic ? `${data.density} active users` : `${data.density} actual user(s)`}
                                  </span>
                                </p>
                                {data.isUserBin && (
                                  <p className="text-brand-peach font-black text-[10px] uppercase tracking-wider mt-1 flex items-center gap-1">
                                    <span className="w-1.5 h-1.5 rounded-full bg-brand-peach animate-pulse"></span>
                                    Your Cohort Standing
                                  </p>
                                )}
                              </div>
                            );
                          }
                          return null;
                        }}
                      />
                      <Bar
                        dataKey="percentage"
                        radius={[0, 4, 4, 0]}
                        barSize={10}
                      >
                        {binData.map((entry, index) => (
                          <Cell
                            key={`cell-${index}`}
                            fill={entry.isUserBin ? '#EC8F8D' : '#44A194'}
                            fillOpacity={entry.isUserBin ? 0.95 : 0.75}
                          />
                        ))}
                      </Bar>
                    </BarChart>
                  </ResponsiveContainer>
                )}
              </div>
            </div>

          </div>
        )}

        {/* 24-Hour Difference Heatmap (Divergence Anomaly Grid) */}
        {hasSelectedPlatforms && !isPopLoading && popData && (
          <div className="bg-white border border-brand-navy/10 rounded-3xl p-4 sm:p-6 shadow-sm space-y-6">

            {/* Heatmap Header (identical to BehavioralHeatmap header) */}
            <div className="flex flex-col sm:flex-row sm:items-center sm:justify-between gap-4 pb-4 border-b border-brand-navy/5">
              <div className="flex items-center gap-3">
                <div className="w-10 h-10 rounded-xl bg-brand-navy/5 flex items-center justify-center text-brand-navy">
                  <Clock className="w-5 h-5" />
                </div>
                <div>
                  <h3 className="font-bold text-brand-navy text-lg">24-Hour Comparative Anomaly Matrix</h3>
                  <p className="text-xs text-brand-navy/50">
                    Hour-by-hour watch-time divergence (User vs. Platform Average).
                  </p>
                </div>
              </div>

              <div className="text-right flex items-center gap-2 bg-brand-beige/50 px-3 py-1.5 rounded-xl border border-brand-navy/5 text-xs text-brand-navy/70 font-semibold self-start sm:self-center">
                <Info className="w-3.5 h-3.5 text-brand-teal" />
                <span>Divergence Analysis</span>
              </div>
            </div>

            {/* Heatmap Grid: show placeholder when population API is unavailable */}
            {!hasPopulationData ? (
              <div className="text-center p-12 py-16 space-y-3 max-w-md mx-auto bg-brand-beige/10 rounded-2xl border border-brand-navy/5">
                <Clock className="w-10 h-10 text-brand-navy/25 mx-auto" />
                <p className="text-sm font-bold text-brand-navy">No comparison for this range</p>
                <p className="text-xs text-brand-navy/50 leading-relaxed">{tooFewPeople ? unavailableMessage : 'Hour-by-hour divergence analysis appears once the selected range contains YouTube watch history.'}</p>
              </div>
            ) : (
              <div className="space-y-4">
                <div className="grid grid-cols-4 sm:grid-cols-6 md:grid-cols-8 lg:grid-cols-12 gap-3">
                  {popData.hourlyAverages.map((row) => {
                  const userHrs = row.userAvg ?? 0;
                  const popHrs = row.populationAvg ?? 0;
                  const diff = userHrs - popHrs;
                  const cappedDiff = Math.max(-0.8, Math.min(0.8, diff));

                  let colorClass = 'bg-brand-navy/5 border-brand-navy/5 text-brand-navy/30';
                  let labelColor = 'text-brand-navy/70';

                  if (cappedDiff > 0.05) {
                    // More active than average = higher screentime (Peach/Red intensity shades)
                    const ratio = cappedDiff / 0.8;
                    if (ratio < 0.25) colorClass = 'bg-brand-peach/10 border-brand-peach/10 text-brand-peach/90';
                    else if (ratio < 0.6) colorClass = 'bg-brand-peach/30 border-brand-peach/20 text-brand-peach';
                    else if (ratio < 0.85) colorClass = 'bg-brand-peach/60 border-brand-peach/30 text-white';
                    else colorClass = 'bg-brand-peach border-brand-peach/50 text-white font-black';

                    labelColor = ratio >= 0.6 ? 'text-white' : 'text-brand-peach font-black';
                  } else if (cappedDiff < -0.05) {
                    // Less active than average = lower screentime (Teal/Green intensity shades)
                    const ratio = Math.abs(cappedDiff) / 0.8;
                    if (ratio < 0.25) colorClass = 'bg-brand-teal/10 border-brand-teal/10 text-brand-teal/90';
                    else if (ratio < 0.6) colorClass = 'bg-brand-teal/30 border-brand-teal/20 text-brand-teal';
                    else if (ratio < 0.85) colorClass = 'bg-brand-teal/60 border-brand-teal/30 text-white';
                    else colorClass = 'bg-brand-teal border-brand-teal/50 text-white font-black';

                    labelColor = ratio >= 0.6 ? 'text-white' : 'text-brand-teal font-black';
                  } else {
                    // Neutral / matching average
                    colorClass = 'bg-brand-beige/25 border-brand-navy/10 text-brand-navy/50';
                    labelColor = 'text-brand-navy font-bold';
                  }

                  const hourNum = parseInt(row.hour);
                  const ampm = hourNum >= 12 ? 'PM' : 'AM';
                  const displayHour = hourNum % 12 === 0 ? 12 : hourNum % 12;

                  return (
                    <div
                      key={row.hour}
                      className={`group relative rounded-xl border p-3 flex flex-col items-center justify-between min-h-[72px] transition-all duration-150 cursor-help ${colorClass}`}
                    >
                      {/* Hour Label */}
                      <span className="text-[10px] font-extrabold uppercase tracking-wide opacity-80">
                        {displayHour} {ampm}
                      </span>

                      {/* Divergence primary value */}
                      <span className={`text-xs font-black tracking-tight mt-1`}>
                        {diff >= 0 ? '+' : ''}{diff.toFixed(1)}h
                      </span>

                      {/* Secondary absolute user vs population value */}
                      <span className="text-[8px] uppercase tracking-wider opacity-65 font-bold mt-0.5">
                        U:{(userHrs).toFixed(1)}h | P:{(popHrs).toFixed(1)}h
                      </span>

                      {/* Hover detailed tooltip */}
                      <div className="pointer-events-none absolute bottom-full left-1/2 z-50 mb-2 w-52 -translate-x-1/2 scale-90 rounded-xl bg-brand-navy p-3 text-left text-xs font-medium text-white opacity-0 shadow-xl transition-all duration-150 group-hover:scale-100 group-hover:opacity-100 border border-white/10">
                        <div className="flex justify-between items-center font-bold text-white border-b border-white/10 pb-1 mb-1">
                          <span>{row.hour} - {`${(hourNum + 1).toString().padStart(2, '0')}:00`}</span>
                          <span className="text-[10px] px-1.5 py-0.5 rounded bg-brand-teal text-white">Hour {hourNum}</span>
                        </div>
                        <div className="space-y-0.5 mt-1">
                          <p className="flex justify-between">
                            <span>Your Average:</span>
                            <span className="font-mono font-bold">{(userHrs * 60).toFixed(0)} mins</span>
                          </p>
                          <p className="flex justify-between text-white/70">
                            <span>Population Avg:</span>
                            <span className="font-mono">{(popHrs * 60).toFixed(0)} mins</span>
                          </p>
                          <p className={`flex justify-between border-t border-white/10 pt-1 mt-1 font-bold ${diff >= 0.05 ? 'text-brand-peach' : diff <= -0.05 ? 'text-brand-teal' : 'text-white/60'}`}>
                            <span>Divergence:</span>
                            <span className="font-mono">
                              {diff >= 0 ? '+' : ''}{(diff * 60).toFixed(0)} mins
                            </span>
                          </p>
                        </div>
                      </div>

                    </div>
                  );
                })}
              </div>

              {/* Heatmap Legend */}
              <div className="flex items-center justify-end gap-3 mt-6 text-xs text-brand-navy/60 font-semibold px-1">
                <span>Less Active (Good)</span>
                <div className="flex items-center gap-1 select-none">
                  <span className="w-4 h-4 rounded bg-brand-teal border border-brand-teal/50" title="Significantly less active"></span>
                  <span className="w-4 h-4 rounded bg-brand-teal/30 border border-brand-teal/20" title="Slightly less active"></span>
                  <span className="w-4 h-4 rounded bg-brand-beige/25 border border-brand-navy/10" title="Neutral / Average"></span>
                  <span className="w-4 h-4 rounded bg-brand-peach/30 border border-brand-peach/20" title="Slightly more active"></span>
                  <span className="w-4 h-4 rounded bg-brand-peach border border-brand-peach/50" title="Significantly more active"></span>
                </div>
                <span>More Active (Harmful)</span>
              </div>
            </div>
            )}

          </div>
        )}

      </div>
  );

  return (
    <ConsoleShell
      activeTab="population"
      backend={backend}
      session={session}
      onResetView={handleResetView}
      awaitingDescription="Upon file ingestion, your usage will be placed against the population benchmark."
      processingDescription="Our background ingestion worker is processing your archive. Population standings appear as soon as your watch history is imported."
    >
      {content}
    </ConsoleShell>
  );
}

export default function PopulationDashboardContainer() {
  const [queryClient] = useState(createConsoleQueryClient);
  return (
    <QueryClientProvider client={queryClient}>
      <PopulationDashboardContent />
    </QueryClientProvider>
  );
}
