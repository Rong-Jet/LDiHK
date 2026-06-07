import React, { useState, useMemo } from 'react';
import { 
  AreaChart, Area, XAxis, YAxis, CartesianGrid,
  Tooltip, ResponsiveContainer 
} from 'recharts';
import { Calendar, Filter, Layers, CheckSquare, Square, ChevronDown, ChevronUp } from 'lucide-react';
import type { FlattenedTimelineRecord } from '../hooks/useAnalyticsData';

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

  datasets?: Record<string, { status: string; min_date?: string; max_date?: string }>;
  dateBounds?: { minDate: string; maxDate: string };
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
const PRESETS = ['1D', '7D', '15D', '30D', '1Y', '5Y', 'all'];

const parseUtcDate = (dateString: string) => {
  const [year, month, day] = dateString.split('-').map(Number);
  return new Date(Date.UTC(year, month - 1, day));
};

const formatUtcDate = (date: Date) => date.toISOString().split('T')[0];

const clampStartDate = (start: string, minDate?: string) => (
  minDate && start < minDate ? minDate : start
);

const getPresetRange = (preset: string, referenceDate: string, minDate?: string) => {
  const refDateObj = parseUtcDate(referenceDate);
  let start = referenceDate;

  if (preset === '7D') {
    refDateObj.setUTCDate(refDateObj.getUTCDate() - 6);
    start = formatUtcDate(refDateObj);
  } else if (preset === '15D') {
    refDateObj.setUTCDate(refDateObj.getUTCDate() - 14);
    start = formatUtcDate(refDateObj);
  } else if (preset === '30D') {
    refDateObj.setUTCDate(refDateObj.getUTCDate() - 29);
    start = formatUtcDate(refDateObj);
  } else if (preset === '1Y') {
    refDateObj.setUTCFullYear(refDateObj.getUTCFullYear() - 1);
    refDateObj.setUTCDate(refDateObj.getUTCDate() + 1);
    start = formatUtcDate(refDateObj);
  } else if (preset === '5Y') {
    refDateObj.setUTCFullYear(refDateObj.getUTCFullYear() - 5);
    refDateObj.setUTCDate(refDateObj.getUTCDate() + 1);
    start = formatUtcDate(refDateObj);
  } else if (preset === 'all') {
    start = minDate || referenceDate;
  }

  return { start: clampStartDate(start, minDate), end: referenceDate };
};

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

    const intersectionMin = readyBounds
      .map((dataset) => dataset.min_date)
      .sort()
      .at(-1) || FALLBACK_REFERENCE_DATE;
    const intersectionMax = readyBounds
      .map((dataset) => dataset.max_date)
      .sort()[0] || FALLBACK_REFERENCE_DATE;

    if (intersectionMin <= intersectionMax) {
      return { minDate: intersectionMin, maxDate: intersectionMax };
    }

    const unionDates = readyBounds.flatMap((dataset) => [dataset.min_date, dataset.max_date]).sort();
    return {
      minDate: unionDates[0] || FALLBACK_REFERENCE_DATE,
      maxDate: unionDates.at(-1) || FALLBACK_REFERENCE_DATE,
    };
  }, [activePlatforms, datasets, dateBounds]);

  const referenceDate = activeDateBounds.maxDate || dateBounds?.maxDate || endDate || FALLBACK_REFERENCE_DATE;

  // Determine active preset label based on startDate
  const activePreset = useMemo(() => {
    if (endDate !== referenceDate) return 'custom';

    for (const preset of PRESETS) {
      const range = getPresetRange(preset, referenceDate, activeDateBounds.minDate);
      if (startDate === range.start) return preset;
    }

    return 'custom';
  }, [activeDateBounds.minDate, endDate, referenceDate, startDate]);

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
    <div className="bg-white border border-brand-navy/10 rounded-3xl p-6 shadow-sm space-y-6">
      {/* Controls Bar */}
      <div className="flex flex-col xl:flex-row xl:items-center xl:justify-between gap-4 pb-4 border-b border-brand-navy/5">
        <div className="flex items-center gap-3">
          <div className="w-10 h-10 rounded-xl bg-brand-navy/5 flex items-center justify-center text-brand-navy">
            <Layers className="w-5 h-5" />
          </div>
          <div>
            <h3 className="font-bold text-brand-navy text-lg">Daily Watchtime Allocation</h3>
            <p className="text-xs text-brand-navy/50">Stacked area representation of hours used per day.</p>
          </div>
        </div>

        <div className="flex flex-wrap items-center gap-3">
          {/* Preset Buttons Grid */}
          <div className="flex items-center bg-brand-beige/60 p-1 rounded-xl border border-brand-navy/5 flex-wrap">
            {['1D', '7D', '15D', '30D', '1Y', '5Y', 'all'].map((preset) => (
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
              const ready = [];
              if (datasets?.['youtube']?.status === 'READY') ready.push('youtube');
              if (datasets?.['instagram']?.status === 'READY') ready.push('instagram');
              if (datasets?.['tiktok']?.status === 'READY') ready.push('tiktok');
              if (datasets?.['spotify']?.status === 'READY') ready.push('spotify');
              if (ready.length > 0) setActivePlatforms(ready);
            }}
            className="text-[10px] uppercase tracking-wider font-extrabold text-brand-teal hover:underline cursor-pointer"
          >
            Select All
          </button>
          <span className="text-brand-navy/25 text-xs">|</span>
          <button
            onClick={() => {
              if (datasets?.['youtube']?.status === 'READY') {
                setActivePlatforms(['youtube']);
              }
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
              data={data}
              margin={{ top: 10, right: 10, left: -20, bottom: 0 }}
              onClick={(state) => {
                if (state && state.activeLabel) {
                  onSelectDate(state.activeLabel);
                }
              }}
              className="cursor-pointer"
            >
              <CartesianGrid strokeDasharray="3 3" stroke="#537D96" strokeOpacity={0.07} />
              <XAxis 
                dataKey="date" 
                tickFormatter={(str) => {
                  const parts = str.split('-');
                  if (parts.length === 3) {
                    const dateObj = new Date(str);
                    const diffDays = data.length;
                    
                    if (diffDays > 730) {
                      // 5Y / All: Show Year only (e.g. 2024)
                      return dateObj.toLocaleDateString('en-US', { year: 'numeric' });
                    }
                    if (diffDays > 30) {
                      // 1Y: Show Month & Year (e.g. Jun 25)
                      return dateObj.toLocaleDateString('en-US', { month: 'short', year: '2-digit' });
                    }
                    // 7D / 15D / 30D / 1D: Show Month/Day
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
                formatter={(value: any, name: string) => {
                  if (value === null || value === undefined) return null;
                  if (PLATFORM_LABELS[name]) {
                    return [`${value} hrs`, PLATFORM_LABELS[name]];
                  }
                  return [`${value} hrs`, name];
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
            Selected Date: {selectedDate}
          </div>
        )}
      </div>
    </div>
  );
}
