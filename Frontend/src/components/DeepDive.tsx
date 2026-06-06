import React, { useMemo } from 'react';
import { BarChart3, HelpCircle, ArrowRight, Bed, AlertCircle, Lightbulb, TrendingUp } from 'lucide-react';
import type { FlattenedTimelineRecord } from '../hooks/useAnalyticsData';

interface DeepDiveProps {
  selectedDate: string | null;
  dayData: FlattenedTimelineRecord | undefined;
}

const PLATFORM_LABELS: Record<string, string> = {
  youtube: 'YouTube',
  instagram: 'Instagram',
  tiktok: 'TikTok',
  twitter: 'Twitter/X',
  linkedin: 'LinkedIn',
};

const PLATFORM_COLORS: Record<string, string> = {
  youtube: '#537D96',   // brand-navy
  instagram: '#EC8F8D', // brand-peach
  tiktok: '#44A194',    // brand-teal
  twitter: '#8ba6b8',   // light navy
  linkedin: '#66b8ad',  // light teal
};

const PLATFORM_BG_CLASSES: Record<string, string> = {
  youtube: 'bg-brand-navy',
  instagram: 'bg-brand-peach',
  tiktok: 'bg-brand-teal',
  twitter: 'bg-blue-400',
  linkedin: 'bg-teal-600',
};

const PILLAR_HEIGHT_PX = 360;

export default function DeepDive({ selectedDate, dayData }: DeepDiveProps) {
  if (!selectedDate || !dayData) {
    return (
      <div className="bg-brand-beige border border-brand-navy/15 rounded-3xl p-8 h-full flex flex-col items-center justify-center text-center space-y-4 shadow-sm min-h-[500px]">
        <div className="w-12 h-12 rounded-2xl bg-white border border-brand-navy/10 flex items-center justify-center text-brand-navy/40 shadow-sm">
          <HelpCircle className="w-6 h-6" />
        </div>
        <div>
          <h4 className="font-bold text-brand-navy text-base">Select a Date for Deep-Dive</h4>
          <p className="text-xs text-brand-navy/60 max-w-[240px] mt-1.5 leading-relaxed mx-auto">
            Click on any event node in the timeline chart above to inspect platform distribution breakdowns for that day.
          </p>
        </div>
        <div className="flex items-center gap-1.5 text-[10px] text-brand-teal font-extrabold uppercase tracking-wider">
          Interactive Node Mapping active
          <ArrowRight className="w-3.5 h-3.5" />
        </div>
      </div>
    );
  }

  // Calculate platform totals
  const totalActiveHours = dayData.youtubeHours + dayData.instagramHours + dayData.tiktokHours + dayData.twitterHours + dayData.linkedinHours;
  const offlineHours = Math.max(0, 24 - totalActiveHours);
  
  // 1. Stack active segments inside the flex-col-reverse pillar
  // Order: tiktok (bottom), youtube, instagram, twitter, linkedin
  const activePlatformsStack = [
    { key: 'tiktok', count: dayData.tiktokHours },
    { key: 'youtube', count: dayData.youtubeHours },
    { key: 'instagram', count: dayData.instagramHours },
    { key: 'twitter', count: dayData.twitterHours },
    { key: 'linkedin', count: dayData.linkedinHours },
  ].map(p => ({
    ...p,
    label: PLATFORM_LABELS[p.key],
    color: PLATFORM_COLORS[p.key],
    bgClass: PLATFORM_BG_CLASSES[p.key],
    percentage: Math.round((p.count / 24) * 100),
  }));

  const activePlatformsWithUsage = activePlatformsStack.filter(p => p.count > 0);

  // 2. Map slices sequence from top to bottom (matches visual column slices top-to-bottom)
  const topToBottomSlices = useMemo(() => {
    const list = [
      {
        key: 'offline',
        label: 'Offline / Sleep',
        count: offlineHours,
        color: '#537D96',
        bgClass: 'bg-brand-navy/10',
        percentage: Math.round((offlineHours / 24) * 100),
        isOffline: true,
      },
      ...[...activePlatformsWithUsage].reverse(),
    ];

    // Compute ideal target Y position (center of each slice)
    let cumulativeHours = 0;
    const slicesWithPositions = list.map((s) => {
      const startPct = (cumulativeHours / 24) * 100;
      const heightPct = (s.count / 24) * 100;
      const centerPct = startPct + heightPct / 2;
      cumulativeHours += s.count;

      return {
        ...s,
        heightPct,
        targetY: centerPct, // Center as % from top
        actualY: centerPct,  // Initially set to ideal center
      };
    });

    // Solve for label collisions (push labels apart with minimum vertical padding)
    const n = slicesWithPositions.length;
    if (n > 1) {
      const minSpacingPct = 10.5;

      for (let iter = 0; iter < 12; iter++) {
        // Forward pass: push labels down
        for (let i = 0; i < n - 1; i++) {
          if (slicesWithPositions[i + 1].actualY < slicesWithPositions[i].actualY + minSpacingPct) {
            slicesWithPositions[i + 1].actualY = slicesWithPositions[i].actualY + minSpacingPct;
          }
        }

        // Bound check bottom element
        if (slicesWithPositions[n - 1].actualY > 100 - minSpacingPct / 2) {
          slicesWithPositions[n - 1].actualY = 100 - minSpacingPct / 2;
        }

        // Backward pass: push labels up
        for (let i = n - 1; i > 0; i--) {
          if (slicesWithPositions[i - 1].actualY > slicesWithPositions[i].actualY - minSpacingPct) {
            slicesWithPositions[i - 1].actualY = slicesWithPositions[i].actualY - minSpacingPct;
          }
        }

        // Bound check top element
        if (slicesWithPositions[0].actualY < minSpacingPct / 2) {
          slicesWithPositions[0].actualY = minSpacingPct / 2;
        }
      }
    }

    return slicesWithPositions;
  }, [dayData, offlineHours, activePlatformsWithUsage]);

  // Top platform for stats card
  const topPlatform = [...activePlatformsWithUsage].sort((a, b) => b.count - a.count)[0];

  // Dynamic Insight Generator
  const dailyInsight = useMemo(() => {
    if (offlineHours > 16) {
      return {
        type: 'success',
        icon: <Bed className="w-4 h-4 text-brand-teal" />,
        title: 'High Offline Recovery',
        text: 'Screen rest duration is excellent. Good visual recovery and focus block today.',
      };
    }
    if (!topPlatform) {
      return {
        type: 'info',
        icon: <Lightbulb className="w-4 h-4 text-brand-navy" />,
        title: 'System Inactive',
        text: 'No social media streams logged for this specific day window.',
      };
    }
    
    if (topPlatform.key === 'tiktok') {
      return {
        type: 'warning',
        icon: <AlertCircle className="w-4 h-4 text-brand-peach" />,
        title: 'High Short-Form Volume',
        text: 'TikTok accounts for most active hours. Take short breaks to curb passive browsing loops.',
      };
    }
    if (topPlatform.key === 'linkedin') {
      return {
        type: 'success',
        icon: <TrendingUp className="w-4 h-4 text-brand-teal" />,
        title: 'Professional Engagement',
        text: 'LinkedIn usage peaks. Optimal day for networking, messaging, and outbound professional activities.',
      };
    }
    if (topPlatform.key === 'youtube') {
      return {
        type: 'info',
        icon: <Lightbulb className="w-4 h-4 text-brand-navy" />,
        title: 'Long-Form Consumption',
        text: 'YouTube is your top active channel. Video publishing window recommendation: 17:00.',
      };
    }
    return {
      type: 'info',
      icon: <Lightbulb className="w-4 h-4 text-brand-navy" />,
      title: 'Active Day Allocation',
      text: `Social platforms occupied ${totalActiveHours.toFixed(1)} hrs of your day. Balance is stable.`,
    };
  }, [topPlatform, offlineHours, totalActiveHours]);

  return (
    <div className="bg-brand-beige border border-brand-navy/15 rounded-3xl p-6 shadow-sm flex flex-col h-full gap-5 min-h-[500px]">
      {/* Header */}
      <div className="flex items-center gap-3 pb-3 border-b border-brand-navy/10">
        <div className="w-9 h-9 rounded-xl bg-white border border-brand-navy/10 flex items-center justify-center text-brand-teal shadow-sm">
          <BarChart3 className="w-4 h-4" />
        </div>
        <div>
          <h3 className="font-bold text-brand-navy text-sm">24-Hour Day Allocation</h3>
          <span className="text-xs font-semibold text-brand-navy/60">{selectedDate}</span>
        </div>
      </div>

      {/* Aggregate Stats Card */}
      <div className="grid grid-cols-2 gap-3 bg-white/80 p-3 rounded-2xl border border-brand-navy/5">
        <div className="text-left">
          <span className="text-[10px] uppercase tracking-wider font-semibold text-brand-navy/50 block">Total Active Time</span>
          <span className="text-lg font-black text-brand-navy">{totalActiveHours.toFixed(2)} hrs</span>
        </div>
        <div className="text-left border-l border-brand-navy/10 pl-3">
          <span className="text-[10px] uppercase tracking-wider font-semibold text-brand-navy/50 block">Top Channel</span>
          <span className="text-sm font-extrabold text-brand-teal block truncate">
            {topPlatform ? topPlatform.label : 'None (Offline)'}
          </span>
        </div>
      </div>

      {/* Visual Pillar & Label Sync Columns (shifted right with pl-8) */}
      <div 
        className="flex items-stretch gap-0 py-2 relative pl-8"
        style={{ height: `${PILLAR_HEIGHT_PX}px` }}
      >
        {/* Column 1: Vertical 24h Pillar */}
        <div className="relative flex-shrink-0 w-12 h-full">
          <div className="w-full h-full rounded-xl border-2 border-brand-navy/20 bg-white shadow-inner overflow-hidden flex flex-col-reverse">
            {/* Stack active segments */}
            {activePlatformsStack.map((p) => p.count > 0 && (
              <div
                key={p.key}
                className={`${p.bgClass} transition-all duration-300 relative group/segment`}
                style={{ height: `${(p.count / 24) * 100}%` }}
              />
            ))}
            
            {/* Offline space on top */}
            <div
              className="bg-brand-navy/10 border-b border-brand-navy/10 transition-all duration-300 relative group/offline flex items-center justify-center"
              style={{ height: `${(offlineHours / 24) * 100}%` }}
            >
              <Bed className="w-4 h-4 text-brand-navy/25" />
            </div>
          </div>
          
          {/* Y-Axis Labels */}
          <div className="absolute -left-6 top-0 bottom-0 flex flex-col justify-between text-[9px] font-bold text-brand-navy/55 select-none py-1">
            <span>24h</span>
            <span>18h</span>
            <span>12h</span>
            <span>6h</span>
            <span>0h</span>
          </div>
        </div>

        {/* Column 2: SVG Bezier Connectors Overlay */}
        <div className="w-8 relative h-full flex-shrink-0">
          <svg 
            className="absolute inset-0 w-full h-full pointer-events-none" 
            viewBox={`0 0 32 ${PILLAR_HEIGHT_PX}`}
            preserveAspectRatio="none"
          >
            {topToBottomSlices.map((slice) => {
              const targetY = (slice.targetY / 100) * PILLAR_HEIGHT_PX;
              const actualY = (slice.actualY / 100) * PILLAR_HEIGHT_PX;
              return (
                <path
                  key={slice.key}
                  d={`M 0 ${targetY} C 16 ${targetY}, 16 ${actualY}, 32 ${actualY}`}
                  stroke={slice.isOffline ? '#537D96' : slice.color}
                  strokeWidth="1.5"
                  strokeOpacity={slice.isOffline ? 0.25 : 0.65}
                  fill="none"
                  className="transition-all duration-300"
                />
              );
            })}
          </svg>
        </div>

        {/* Column 3: Aligned Labels Column (Absolute positioning with collision resolver) */}
        <div className="flex-grow relative h-full">
          {topToBottomSlices.map((slice) => {
            return (
              <div
                key={slice.key}
                className="absolute left-0 right-0 -translate-y-1/2 flex flex-col justify-center text-left py-1 transition-all duration-300 pointer-events-none"
                style={{ 
                  top: `${slice.actualY}%`,
                }}
              >
                <span className={`font-bold text-xs block truncate pointer-events-auto select-text ${slice.isOffline ? 'text-brand-navy/50' : 'text-brand-navy'}`}>
                  {slice.label}
                </span>
                <span className="text-[10px] text-brand-navy/55 block pointer-events-auto select-text">
                  {slice.count.toFixed(1)} hrs &bull; {slice.percentage}%
                </span>
              </div>
            );
          })}
        </div>
      </div>

      {/* Dynamic Recommendation/Insight Card */}
      <div className="bg-white p-3.5 rounded-2xl border border-brand-navy/10 flex gap-3 text-left shadow-sm">
        <div className="w-8 h-8 rounded-lg bg-brand-beige flex items-center justify-center shrink-0">
          {dailyInsight.icon}
        </div>
        <div>
          <span className="font-extrabold text-xs text-brand-navy block">{dailyInsight.title}</span>
          <p className="text-[11px] text-brand-navy/70 mt-0.5 leading-relaxed">{dailyInsight.text}</p>
        </div>
      </div>

      <div className="text-[10px] text-brand-navy/40 font-semibold text-center border-t border-brand-navy/10 pt-3">
        Connector lines track offset values to map narrow segments.
      </div>
    </div>
  );
}
