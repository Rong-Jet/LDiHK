import React from 'react';
import { Clock, Info } from 'lucide-react';

interface HeatmapCell {
  hour: string;
  value: number;
}

interface BehavioralHeatmapProps {
  data: HeatmapCell[];
  activePlatforms: string[];
  totalScopeHours: number;
  dayCount: number;
}

export default function BehavioralHeatmap({ 
  data, 
  activePlatforms,
  totalScopeHours,
  dayCount,
}: BehavioralHeatmapProps) {
  const maxVal = React.useMemo(() => {
    return Math.max(...data.map((d) => d.value), 0);
  }, [data]);

  // Determine the background intensity class based on cell value relative to maxVal
  const getCellColorClass = (value: number) => {
    if (activePlatforms.length === 0 || value === 0 || maxVal === 0) {
      return 'bg-brand-navy/5 border-brand-navy/5 text-brand-navy/30';
    }
    const ratio = value / maxVal;
    if (ratio < 0.15) return 'bg-brand-teal/10 hover:bg-brand-teal/20 border-brand-teal/10 text-brand-navy/60';
    if (ratio < 0.4) return 'bg-brand-teal/30 hover:bg-brand-teal/40 border-brand-teal/20 text-brand-navy/80';
    if (ratio < 0.65) return 'bg-brand-teal/60 hover:bg-brand-teal/70 border-brand-teal/40 text-white';
    if (ratio < 0.85) return 'bg-brand-teal/80 hover:bg-brand-teal/90 border-brand-teal/50 text-white';
    return 'bg-brand-teal hover:brightness-95 border-brand-teal/60 text-white font-black';
  };

  const isAveraged = dayCount > 1;

  return (
    <div className="bg-white border border-brand-navy/10 rounded-3xl p-6 shadow-sm space-y-6">
      {/* Header */}
      <div className="flex flex-col sm:flex-row sm:items-center sm:justify-between gap-4 pb-4 border-b border-brand-navy/5">
        <div className="flex items-center gap-3">
          <div className="w-10 h-10 rounded-xl bg-brand-navy/5 flex items-center justify-center text-brand-navy">
            <Clock className="w-5 h-5" />
          </div>
          <div>
            <h3 className="font-bold text-brand-navy text-lg">24-Hour Behavioral Heatmap</h3>
            <p className="text-xs text-brand-navy/50">
              {isAveraged 
                ? 'Average daily usage density (watch time hours) across a 24-hour cycle.' 
                : 'Watch time allocation (hours) across a 24-hour cycle.'
              }
            </p>
          </div>
        </div>

        <div className="text-right flex items-center gap-2 bg-brand-beige/50 px-3 py-1.5 rounded-xl border border-brand-navy/5 text-xs text-brand-navy/70 font-semibold self-start sm:self-center">
          <Info className="w-3.5 h-3.5 text-brand-teal" />
          <span>
            {isAveraged 
              ? `Scope Total: ${totalScopeHours.toFixed(1)} hrs (Avg: ${(totalScopeHours / dayCount).toFixed(1)} hrs/day)`
              : `Total Watchtime: ${totalScopeHours.toFixed(1)} hrs`
            }
          </span>
        </div>
      </div>

      {/* Heatmap Grid container */}
      <div className="space-y-4">
        {activePlatforms.length === 0 ? (
          <div className="py-12 bg-brand-beige/20 border border-brand-navy/5 rounded-2xl p-6 text-center">
            <h4 className="font-bold text-brand-navy text-sm">Heatmap Suspended</h4>
            <p className="text-xs text-brand-navy/50 mt-1 max-w-sm mx-auto leading-relaxed">
              Enable one or more platforms in the checklist to calculate hourly aggregate engagement distributions.
            </p>
          </div>
        ) : (
          <div>
            {/* Grid */}
            <div className="grid grid-cols-4 sm:grid-cols-6 md:grid-cols-8 lg:grid-cols-12 gap-3">
              {data.map((cell, index) => {
                const colorClass = getCellColorClass(cell.value);
                const hourNum = parseInt(cell.hour);
                const ampm = hourNum >= 12 ? 'PM' : 'AM';
                const displayHour = hourNum % 12 === 0 ? 12 : hourNum % 12;

                return (
                  <div
                    key={cell.hour}
                    className={`group relative rounded-xl border p-3 flex flex-col items-center justify-between min-h-[72px] transition-all duration-150 cursor-help ${colorClass}`}
                  >
                    <span className="text-[10px] font-extrabold uppercase tracking-wide opacity-80">
                      {displayHour} {ampm}
                    </span>
                    <span className="text-xs font-black tracking-tight mt-1">
                      {cell.value > 0 ? `${cell.value.toFixed(1)}h` : '-'}
                    </span>

                    {/* Tooltip on Hover */}
                    <div className="pointer-events-none absolute bottom-full left-1/2 z-50 mb-2 w-52 -translate-x-1/2 scale-90 rounded-xl bg-brand-navy p-3 text-left text-xs font-medium text-white opacity-0 shadow-xl transition-all duration-150 group-hover:scale-100 group-hover:opacity-100 border border-white/10">
                      <div className="flex justify-between items-center font-bold text-white border-b border-white/10 pb-1 mb-1">
                        <span>{cell.hour} - {`${(hourNum + 1).toString().padStart(2, '0')}:00`}</span>
                        <span className="text-[10px] px-1.5 py-0.5 rounded bg-brand-teal text-white">Hour {index}</span>
                      </div>
                      <p className="text-white/80 font-bold">
                        {isAveraged 
                          ? `Avg Watchtime: ${cell.value.toFixed(2)} hrs/day`
                          : `Watchtime: ${cell.value.toFixed(2)} hrs`
                        }
                      </p>
                      <p className="text-[10px] text-white/60 mt-1">
                        Active sources: {activePlatforms.join(', ')}
                      </p>
                    </div>
                  </div>
                );
              })}
            </div>

            {/* Heatmap Legend */}
            <div className="flex items-center justify-end gap-3 mt-6 text-xs text-brand-navy/60 font-semibold px-1">
              <span>Low Watchtime</span>
              <div className="flex items-center gap-1">
                <span className="w-4 h-4 rounded bg-brand-teal/10 border border-brand-teal/15"></span>
                <span className="w-4 h-4 rounded bg-brand-teal/30 border border-brand-teal/20"></span>
                <span className="w-4 h-4 rounded bg-brand-teal/60 border border-brand-teal/40"></span>
                <span className="w-4 h-4 rounded bg-brand-teal/80 border border-brand-teal/50"></span>
                <span className="w-4 h-4 rounded bg-brand-teal border border-brand-teal/60"></span>
              </div>
              <span>Peak Watchtime</span>
            </div>
          </div>
        )}
      </div>
    </div>
  );
}
