import React, { useState, useMemo } from 'react';
import { 
  AreaChart, Area, Line, XAxis, YAxis, CartesianGrid, 
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

  // Dynamic Trendline Period (number of days)
  trendlinePeriod: number;
  setTrendlinePeriod: (period: number) => void;

  datasets?: Record<string, { status: string; min_date?: string; max_date?: string }>;
  dateBounds?: { minDate: string; maxDate: string };
}

const ALL_PLATFORMS = ['YouTube', 'Instagram', 'TikTok', 'Twitter', 'LinkedIn'];

const PLATFORM_COLORS: Record<string, string> = {
  youtube: '#537D96',   // brand-navy
  instagram: '#EC8F8D', // brand-peach
  tiktok: '#44A194',    // brand-teal
  twitter: '#8ba6b8',   // light navy
  linkedin: '#66b8ad',  // light teal
};

const PLATFORM_LABELS: Record<string, string> = {
  youtubeHours: 'YouTube',
  instagramHours: 'Instagram',
  tiktokHours: 'TikTok',
  twitterHours: 'Twitter/X',
  linkedinHours: 'LinkedIn',
  totalHours: 'Total Active Time',
  smaHours: 'Dynamic SMA',
};

const REFERENCE_DATE = '2026-06-06';

export default function MainTimeline({
  data,
  activePlatforms,
  setActivePlatforms,
  selectedDate,
  onSelectDate,
  startDate,
  endDate,
  setDateRange,
  trendlinePeriod,
  setTrendlinePeriod,
  datasets,
  dateBounds,
}: MainTimelineProps) {
  const [showSMA, setShowSMA] = useState(true);
  const [showAdvancedFilters, setShowAdvancedFilters] = useState(false);

  // Determine active preset label based on startDate
  const activePreset = useMemo(() => {
    if (endDate !== REFERENCE_DATE) return 'custom';
    
    if (startDate === REFERENCE_DATE) return '1D';
    if (startDate === '2026-05-31') return '7D';
    if (startDate === '2026-05-23') return '15D';
    if (startDate === '2026-05-08') return '30D';
    if (startDate === '2025-06-07') return '1Y';
    if (startDate === '2021-06-07') return '5Y';
    if (startDate === '2016-06-06') return 'all';
    
    return 'custom';
  }, [startDate, endDate]);

  // Handle Preset Click
  const applyPreset = (preset: string) => {
    const end = REFERENCE_DATE;
    let start = REFERENCE_DATE;

    const refDateObj = new Date(REFERENCE_DATE);

    if (preset === '1D') {
      start = REFERENCE_DATE;
    } else if (preset === '7D') {
      refDateObj.setDate(refDateObj.getDate() - 6);
      start = refDateObj.toISOString().split('T')[0];
    } else if (preset === '15D') {
      refDateObj.setDate(refDateObj.getDate() - 14);
      start = refDateObj.toISOString().split('T')[0];
    } else if (preset === '30D') {
      refDateObj.setDate(refDateObj.getDate() - 29);
      start = refDateObj.toISOString().split('T')[0];
    } else if (preset === '1Y') {
      refDateObj.setFullYear(refDateObj.getFullYear() - 1);
      refDateObj.setDate(refDateObj.getDate() + 1);
      start = refDateObj.toISOString().split('T')[0];
    } else if (preset === '5Y') {
      refDateObj.setFullYear(refDateObj.getFullYear() - 5);
      refDateObj.setDate(refDateObj.getDate() + 1);
      start = refDateObj.toISOString().split('T')[0];
    } else if (preset === 'all') {
      refDateObj.setFullYear(refDateObj.getFullYear() - 10);
      start = refDateObj.toISOString().split('T')[0];
    }

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

          {/* SMA Toggle */}
          <button
            onClick={() => setShowSMA(!showSMA)}
            className={`px-4 py-2 rounded-xl text-xs font-bold border transition-all flex items-center gap-2 ${
              showSMA
                ? 'bg-brand-peach/10 border-brand-peach/30 text-brand-navy'
                : 'bg-white border-brand-navy/10 text-brand-navy/60 hover:border-brand-navy/20'
            }`}
          >
            <span className={`w-2 h-2 rounded-full ${showSMA ? 'bg-brand-peach' : 'bg-brand-navy/30'}`}></span>
            Trendline
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
                min={dateBounds?.minDate}
                max={dateBounds?.maxDate}
                onChange={(e) => setDateRange(e.target.value, endDate)}
                className="bg-white border border-brand-navy/15 rounded-xl px-3 py-2 text-xs font-bold text-brand-navy focus:outline-none focus:ring-1 focus:ring-brand-teal w-full"
              />
              <span className="text-brand-navy/40 text-xs font-bold">to</span>
              <input
                type="date"
                value={endDate}
                min={dateBounds?.minDate}
                max={dateBounds?.maxDate}
                onChange={(e) => setDateRange(startDate, e.target.value)}
                className="bg-white border border-brand-navy/15 rounded-xl px-3 py-2 text-xs font-bold text-brand-navy focus:outline-none focus:ring-1 focus:ring-brand-teal w-full"
              />
            </div>
            <span className="text-[9px] text-brand-navy/40 block">Queries backend to update chart & matrix scope.</span>
          </div>

          {/* Custom Trendline Period Selector */}
          <div className="space-y-2">
            <label className="text-[10px] uppercase tracking-wider font-extrabold text-brand-navy/60 flex items-center gap-1.5">
              <span className="w-2.5 h-2.5 rounded-full bg-brand-peach"></span>
              Moving Average Trendline Period
            </label>
            <div className="flex items-center gap-3">
              <input
                type="number"
                min="1"
                max="120"
                value={trendlinePeriod}
                onChange={(e) => setTrendlinePeriod(Math.max(1, parseInt(e.target.value) || 7))}
                className="bg-white border border-brand-navy/15 rounded-xl px-3 py-2 text-xs font-bold text-brand-navy focus:outline-none focus:ring-1 focus:ring-brand-teal w-24 text-center"
              />
              <span className="text-xs font-bold text-brand-navy/70">Days Moving Average</span>
            </div>
            <span className="text-[9px] text-brand-navy/40 block">Configure the interval size used for the dynamic trendline computation.</span>
          </div>
        </div>
      )}

      {/* Checklist Legend */}
      <div className="flex flex-wrap items-center justify-between gap-4 bg-brand-beige/30 p-4 rounded-2xl border border-brand-navy/5">
        <div className="flex flex-wrap items-center gap-3">
          {ALL_PLATFORMS.map((platform) => {
            const key = platform.toLowerCase();
            const isYouTube = key === 'youtube';

            if (!isYouTube) {
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
              if (datasets?.['youtube']?.status === 'READY') {
                setActivePlatforms(['youtube']);
              }
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
                  if (name === 'smaHours') {
                    return [`${value} hrs`, `${trendlinePeriod}-Day SMA`];
                  }
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

              {/* Overlay SMA trendline of total active watch hours if toggled */}
              {showSMA && (
                <Line
                  type="monotone"
                  dataKey="smaHours"
                  stroke="#537D96"
                  strokeWidth={2}
                  strokeDasharray="4 4"
                  dot={false}
                  activeDot={false}
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
            <span>Stacked Platform Allocations (Smoothed)</span>
          </div>
          {showSMA && (
            <div className="flex items-center gap-1.5">
              <span className="w-3.5 h-1 border-t-2 border-dashed border-brand-navy"></span>
              <span>{trendlinePeriod}-Day SMA of Total Hours</span>
            </div>
          )}
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
