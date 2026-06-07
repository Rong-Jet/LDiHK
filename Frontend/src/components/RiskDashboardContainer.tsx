import React, { useState, useEffect, useMemo } from 'react';
import { QueryClient, QueryClientProvider, useQuery, useQueryClient } from '@tanstack/react-query';
import { 
  RefreshCw, BarChart3, Database, ShieldAlert, UploadCloud,
  Key, Copy, Check, LogOut, Eye, EyeOff, ShieldCheck, Lock,
  Clock, Activity, Info, Sparkles, AlertCircle, Bed, BookOpen, 
  ChevronRight, Heart, AlertTriangle, Filter, ChevronDown, ChevronUp,
  Calendar
} from 'lucide-react';
import { 
  AreaChart, Area, XAxis, YAxis, Tooltip, ResponsiveContainer, 
  CartesianGrid, ReferenceLine
} from 'recharts';
import UploadZone from './UploadZone';

const IS_MOCK_MODE = import.meta.env.PUBLIC_MOCK_API === 'true';
const API_BASE = IS_MOCK_MODE ? '' : (import.meta.env.PUBLIC_API_URL || '');

const queryClient = new QueryClient({
  defaultOptions: {
    queries: {
      refetchOnWindowFocus: false,
      retry: 1,
    },
  },
});

interface QueryRow {
  date: string;
  hour: number;
  event_count: number;
  estimated_watch_seconds: number;
}

// Client-side simulation generator removed to rely on consistent backend mock API

function RiskDashboardContent() {
  const queryClient = useQueryClient();
  const [showUploadZone, setShowUploadZone] = useState(false);
  const [showAdvancedFilters, setShowAdvancedFilters] = useState(false);
  
  // Date range filters matching the timeline selection
  const [startDate, setStartDate] = useState('2026-05-08');
  const [endDate, setEndDate] = useState('2026-06-06');

  const [sessionToken, setSessionToken] = useState<string | null>(() => {
    if (typeof window !== 'undefined') {
      return localStorage.getItem('ldihk_session_token') || null;
    }
    return null;
  });

  const [loginIdInput, setLoginIdInput] = useState('');
  const [showLoginPassword, setShowLoginPassword] = useState(false);
  const [copiedToken, setCopiedToken] = useState(false);
  const [showToken, setShowToken] = useState(false);

  const handleLoginSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    const cleanToken = loginIdInput.trim();
    if (cleanToken) {
      localStorage.setItem('ldihk_session_token', cleanToken);
      setSessionToken(cleanToken);
    }
  };

  const handleSessionGenerated = (newToken: string) => {
    localStorage.setItem('ldihk_session_token', newToken);
    setSessionToken(newToken);
  };

  const handleLogout = () => {
    localStorage.removeItem('ldihk_session_token');
    localStorage.removeItem('ldihk_current_import_id');
    setSessionToken(null);
    setLoginIdInput('');
    queryClient.clear();
  };

  const copyToClipboard = () => {
    if (sessionToken) {
      navigator.clipboard.writeText(sessionToken);
      setCopiedToken(true);
      setTimeout(() => setCopiedToken(false), 2000);
    }
  };

  const [currentImportId, setCurrentImportId] = useState<string | null>(() => {
    if (typeof window !== 'undefined') {
      return localStorage.getItem('ldihk_current_import_id') || null;
    }
    return null;
  });

  // Session Probe Query (Fetches active dates to discover dataset bounds)
  const { data: probeData, refetch: refetchProbe } = useQuery({
    queryKey: ['probe', sessionToken],
    queryFn: async () => {
      if (!sessionToken) return null;
      const res = await fetch(`${API_BASE}/api/query`, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          'Authorization': `Bearer ${sessionToken}`
        },
        body: JSON.stringify({
          dataset: 'youtube_usage',
          metrics: ['event_count'],
          dimensions: ['date'],
          filters: {
            start_date: '2015-01-01',
            end_date: '2026-12-31',
          },
          options: {
            include_zero_buckets: false
          }
        })
      });
      if (!res.ok) return { rows: [] };
      return res.json();
    },
    enabled: !IS_MOCK_MODE && !!sessionToken && !currentImportId,
  });

  // Import Polling Query
  const { data: importStatusData } = useQuery({
    queryKey: ['importStatus', currentImportId, sessionToken],
    queryFn: async () => {
      const res = await fetch(`${API_BASE}/api/imports/${currentImportId}`, {
        headers: {
          'Authorization': `Bearer ${sessionToken}`
        }
      });
      if (!res.ok) throw new Error('Import status query failed');
      return res.json();
    },
    enabled: !IS_MOCK_MODE && !!currentImportId && !!sessionToken,
    refetchInterval: (query) => {
      const status = query.state.data?.status;
      return (status === 'queued' || status === 'running') ? 1000 : false;
    },
  });

  useEffect(() => {
    if (importStatusData?.status === 'completed' || importStatusData?.status === 'failed') {
      localStorage.removeItem('ldihk_current_import_id');
      refetchProbe();
      setCurrentImportId(null);
    }
  }, [importStatusData?.status, refetchProbe]);

  const currentStatus = IS_MOCK_MODE 
    ? 'READY'
    : (currentImportId 
      ? 'PROCESSING' 
      : (probeData?.rows && probeData.rows.length > 0 ? 'READY' : 'NOT_UPLOADED'));

  const paddedStartDate = useMemo(() => {
    if (!startDate) return '';
    const dateObj = new Date(startDate);
    dateObj.setDate(dateObj.getDate() - 90);
    return dateObj.toISOString().split('T')[0];
  }, [startDate]);

  const readyPlatforms = IS_MOCK_MODE 
    ? ['youtube', 'instagram', 'tiktok', 'spotify'] 
    : (currentStatus === 'READY' ? ['youtube'] : []);

  // Discovered Date Bounds
  const discoveredBounds = React.useMemo(() => {
    if (IS_MOCK_MODE) {
      const tenYearsAgo = new Date();
      tenYearsAgo.setFullYear(tenYearsAgo.getFullYear() - 10);
      return {
        minDate: tenYearsAgo.toISOString().split('T')[0],
        maxDate: '2026-06-06',
      };
    }
    if (!probeData?.rows || probeData.rows.length === 0) {
      return { minDate: '2026-05-08', maxDate: '2026-06-06' };
    }
    const dates = probeData.rows.map((r: any) => r.date).sort();
    return {
      minDate: dates[0],
      maxDate: dates[dates.length - 1],
    };
  }, [probeData]);

  // Automatically update start and end dates when date bounds are discovered (Only in Live Mode)
  React.useEffect(() => {
    if (!IS_MOCK_MODE && discoveredBounds.minDate && discoveredBounds.maxDate) {
      const [y, m, d] = discoveredBounds.maxDate.split('-').map(Number);
      const maxDateObj = new Date(Date.UTC(y, m - 1, d));
      const minDateObj = new Date(discoveredBounds.minDate);
      const diffDays = Math.round((maxDateObj.getTime() - minDateObj.getTime()) / (1000 * 3600 * 24));

      if (diffDays > 90) {
        const defaultStart = new Date(maxDateObj);
        defaultStart.setUTCDate(defaultStart.getUTCDate() - 29);
        setStartDate(defaultStart.toISOString().split('T')[0]);
        setEndDate(discoveredBounds.maxDate);
      } else {
        setStartDate(discoveredBounds.minDate);
        setEndDate(discoveredBounds.maxDate);
      }
    }
  }, [discoveredBounds.minDate, discoveredBounds.maxDate]);

  // Main custom query to retrieve granular hourly-daily watch records for wellness analysis
  const { data: detailedUsageData, isLoading: isDetailedLoading, error: detailedError } = useQuery<{ rows: QueryRow[] }>({
    queryKey: ['detailedUsage', readyPlatforms.join(','), paddedStartDate, endDate, sessionToken],
    queryFn: async () => {
      if (readyPlatforms.length === 0) return { rows: [] };
      
      const promises = readyPlatforms.map(async (platform) => {
        const res = await fetch(`${API_BASE}/api/query`, {
          method: 'POST',
          headers: {
            'Content-Type': 'application/json',
            'Authorization': `Bearer ${sessionToken}`
          },
          body: JSON.stringify({
            dataset: `${platform}_usage`,
            metrics: ['event_count', 'estimated_watch_seconds'],
            dimensions: ['date', 'hour'],
            filters: {
              start_date: paddedStartDate,
              end_date: endDate,
            },
            options: {
              include_zero_buckets: true,
              limit: 1000
            }
          })
        });
        if (!res.ok) throw new Error(`Failed to load detailed usage logs for ${platform}`);
        const data = await res.json();
        return data.rows as QueryRow[];
      });

      const results = await Promise.all(promises);
      
      // Combine results by grouping by date and hour
      const combinedMap: { [key: string]: QueryRow } = {};
      results.forEach(rows => {
        rows.forEach(r => {
          const key = `${r.date}_${r.hour}`;
          if (!combinedMap[key]) {
            combinedMap[key] = {
              date: r.date,
              hour: r.hour,
              event_count: 0,
              estimated_watch_seconds: 0
            };
          }
          combinedMap[key].event_count += r.event_count;
          combinedMap[key].estimated_watch_seconds += r.estimated_watch_seconds;
        });
      });

      return { rows: Object.values(combinedMap) };
    },
    enabled: (IS_MOCK_MODE || currentStatus === 'READY') && !!sessionToken && readyPlatforms.length > 0,
  });

  const handleUploadComplete = async (s3Key: string, s3Bucket: string) => {
    try {
      const res = await fetch(`${API_BASE}/api/imports`, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          'Authorization': `Bearer ${sessionToken}`
        },
        body: JSON.stringify({
          s3_bucket: s3Bucket,
          s3_key: s3Key,
        })
      });
      if (!res.ok) throw new Error('Failed to register import');
      const data = await res.json();
      localStorage.setItem('ldihk_current_import_id', data.import_id);
      setCurrentImportId(data.import_id);
    } catch (err) {
      console.error('Error starting import:', err);
    }
  };

  const handleResetPipeline = async () => {
    try {
      await fetch('/api/upload-url'); 
      setStartDate('2026-05-08');
      setEndDate('2026-06-06');
      
      queryClient.setQueryData(['probe', sessionToken], null);
      queryClient.setQueryData(['detailedUsage'], null);
      localStorage.removeItem('ldihk_current_import_id');
      setCurrentImportId(null);
      queryClient.invalidateQueries({ queryKey: ['probe'] });
    } catch (err) {
      console.error('Failed to reset pipeline:', err);
    }
  };

  // Preset Date range selection logic
  const activePreset = useMemo(() => {
    const REFERENCE_DATE = !IS_MOCK_MODE ? (discoveredBounds.maxDate || '2026-06-06') : '2026-06-06';
    if (endDate !== REFERENCE_DATE) return 'custom';
    
    if (startDate === REFERENCE_DATE) return '1D';
    
    const refDateObj = new Date(REFERENCE_DATE);
    
    const d7 = new Date(refDateObj);
    d7.setDate(d7.getDate() - 6);
    if (startDate === d7.toISOString().split('T')[0]) return '7D';
    
    const d15 = new Date(refDateObj);
    d15.setDate(d15.getDate() - 14);
    if (startDate === d15.toISOString().split('T')[0]) return '15D';
    
    const d30 = new Date(refDateObj);
    d30.setDate(d30.getDate() - 29);
    if (startDate === d30.toISOString().split('T')[0]) return '30D';
    
    const d1y = new Date(refDateObj);
    d1y.setFullYear(d1y.getFullYear() - 1);
    d1y.setDate(d1y.getDate() + 1);
    if (startDate === d1y.toISOString().split('T')[0]) return '1Y';
    
    const d5y = new Date(refDateObj);
    d5y.setFullYear(d5y.getFullYear() - 5);
    d5y.setDate(d5y.getDate() + 1);
    if (startDate === d5y.toISOString().split('T')[0]) return '5Y';
    
    const dall = new Date(refDateObj);
    dall.setFullYear(dall.getFullYear() - 10);
    if (startDate === dall.toISOString().split('T')[0]) return 'all';

    return 'custom';
  }, [startDate, endDate, discoveredBounds.maxDate]);

  const applyPreset = (preset: string) => {
    const end = !IS_MOCK_MODE ? (discoveredBounds.maxDate || '2026-06-06') : '2026-06-06';
    let start = end;
    const refDateObj = new Date(end);

    if (preset === '1D') {
      start = end;
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

    setStartDate(start);
    setEndDate(end);
  };

  // RISK COMPUTATION ENGINE (Wellness Score calculation)
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
      const z = -2.1 + (0.35 * ytHours) + (0.80 * fragmentationIndex) + (1.20 * ytLateNightHours);

      const riskProbability = 1 / (1 + Math.exp(-z));
      const riskScorePercent = parseFloat((riskProbability * 100).toFixed(1));

      return {
        date: dateStr,
        riskScore: riskScorePercent,
        volume: parseFloat(ytHours.toFixed(2)),
        lateNightHours: parseFloat(ytLateNightHours.toFixed(2)),
        fragmentation: Math.round(fragmentationIndex * 100), 
      };
    });

    const visibleTimelineData = timelineData.filter(d => d.date >= startDate && d.date <= endDate);
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

    const smoothWindow = visibleTotalDays > 1825 ? 60 : (visibleTotalDays > 365 ? 30 : (visibleTotalDays > 30 ? 7 : 1));
    const smoothedTimelineData = timelineData.map((record, index) => {
      if (smoothWindow <= 1) return record;
      const start = Math.max(0, index - smoothWindow + 1);
      const count = index - start + 1;
      let riskSum = 0;
      let volSum = 0;
      let lateSum = 0;
      let fragSum = 0;
      for (let j = start; j <= index; j++) {
        riskSum += timelineData[j].riskScore;
        volSum += timelineData[j].volume;
        lateSum += timelineData[j].lateNightHours;
        fragSum += timelineData[j].fragmentation;
      }
      return {
        date: record.date,
        riskScore: parseFloat((riskSum / count).toFixed(1)),
        volume: parseFloat((volSum / count).toFixed(2)),
        lateNightHours: parseFloat((lateSum / count).toFixed(2)),
        fragmentation: Math.round(fragSum / count),
      };
    });

    const filteredSmoothedTimelineData = smoothedTimelineData.filter(d => d.date >= startDate && d.date <= endDate);

    return {
      timelineData: filteredSmoothedTimelineData,
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
  }, [detailedUsageData, startDate, endDate]);

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

  if (!sessionToken) {
    return (
      <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 py-10 text-left">
        <div className="mb-10 pb-6 border-b border-brand-navy/10">
          <h1 className="text-3xl font-extrabold text-brand-navy tracking-tight">Analytics Console</h1>
          <p className="text-sm text-brand-navy/60 mt-1">Manage, process, and query your social media data pipelines.</p>
        </div>

        <div className="bg-white border border-brand-navy/15 rounded-[32px] overflow-hidden shadow-2xl relative">
          <div className="absolute top-0 left-0 right-0 h-1.5 bg-gradient-to-r from-brand-teal via-brand-peach to-brand-teal"></div>
          
          <div className="grid grid-cols-1 md:grid-cols-2">
            <div className="p-8 sm:p-12 border-b md:border-b-0 md:border-r border-brand-navy/10 flex flex-col justify-between space-y-8 bg-brand-beige/10">
              <div className="space-y-4">
                <div className="w-12 h-12 rounded-2xl bg-brand-teal/10 flex items-center justify-center text-brand-teal shadow-inner">
                  <Lock className="w-6 h-6" />
                </div>
                <div>
                  <h2 className="text-2xl font-black text-brand-navy tracking-tight">Access Your Console</h2>
                  <p className="text-xs text-brand-navy/60 mt-1 leading-relaxed">
                    Enter your unique word-combination LDiHK-ID to retrieve your saved analytics dashboard.
                  </p>
                </div>
              </div>

              <form onSubmit={handleLoginSubmit} className="space-y-4">
                <input 
                  type="text" 
                  name="username" 
                  value="LDiHK User" 
                  readOnly 
                  style={{ display: 'none' }} 
                  autoComplete="username" 
                />
                
                <div className="space-y-1.5">
                  <label className="text-[10px] uppercase tracking-wider font-extrabold text-brand-navy/50 block">
                    Your LDiHK-ID
                  </label>
                  <div className="relative">
                    <input
                      type={showLoginPassword ? 'text' : 'password'}
                      name="password"
                      value={loginIdInput}
                      onChange={(e) => setLoginIdInput(e.target.value)}
                      placeholder="e.g. ldihk-cosmic-pegasus-soaring"
                      autoComplete="current-password"
                      required
                      className="w-full bg-white border border-brand-navy/20 rounded-2xl pl-4 pr-12 py-3.5 text-sm font-bold text-brand-navy placeholder-brand-navy/30 focus:outline-none focus:ring-2 focus:ring-brand-teal/30 focus:border-brand-teal transition-all"
                    />
                    <button
                      type="button"
                      onClick={() => setShowLoginPassword(!showLoginPassword)}
                      className="absolute right-3.5 top-1/2 -translate-y-1/2 text-brand-navy/40 hover:text-brand-navy transition-colors cursor-pointer"
                    >
                      {showLoginPassword ? <EyeOff className="w-4 h-4" /> : <Eye className="w-4 h-4" />}
                    </button>
                  </div>
                </div>

                <button
                  type="submit"
                  className="w-full px-5 py-4 rounded-2xl bg-brand-navy hover:bg-brand-navy/95 text-white font-bold text-sm transition-all shadow-md shadow-brand-navy/10 hover:shadow-lg duration-150 flex items-center justify-center gap-2 cursor-pointer"
                >
                  <Key className="w-4 h-4 text-brand-peach" />
                  Access Dashboard
                </button>
              </form>

              <div className="text-[10px] text-brand-navy/40 text-center font-medium">
                Note: LDiHK-IDs are strictly anonymous and securely indexed.
              </div>
            </div>

            <div className="p-8 sm:p-12 flex flex-col justify-between space-y-8">
              <div className="space-y-4">
                <div className="w-12 h-12 rounded-2xl bg-brand-peach/10 flex items-center justify-center text-brand-peach shadow-inner">
                  <UploadCloud className="w-6 h-6" />
                </div>
                <div>
                  <h2 className="text-2xl font-black text-brand-navy tracking-tight">Initialize Workspace</h2>
                  <p className="text-xs text-brand-navy/60 mt-1 leading-relaxed">
                    No ID yet? Drag & drop your first ZIP export archive below. We'll generate a secure, anonymous LDiHK-ID for you on upload.
                  </p>
                </div>
              </div>

              <div className="w-full">
                <UploadZone 
                  sessionToken={null} 
                  onSessionGenerated={handleSessionGenerated}
                  onUploadComplete={handleUploadComplete}
                />
              </div>

              <div className="text-[10px] text-brand-navy/40 text-center font-medium flex items-center justify-center gap-1">
                <ShieldCheck className="w-3.5 h-3.5 text-brand-teal" />
                Requires explicit privacy consent warning agreement.
              </div>
            </div>
          </div>
        </div>
      </div>
    );
  }

  return (
    <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 py-10 font-sans">
      {/* Header and Controller Row */}
      <div className="mb-6 flex flex-col md:flex-row md:items-center md:justify-between gap-6 pb-6 border-b border-brand-navy/10 text-left">
        <div>
          <h1 className="text-3xl font-extrabold text-brand-navy tracking-tight">Analytics Console</h1>
          <p className="text-sm text-brand-navy/60 mt-1">Manage, process, and query your social media data pipelines.</p>
        </div>

        <div className="flex flex-wrap items-center gap-3">
          <div className="flex items-center gap-2 bg-white border border-brand-navy/10 rounded-xl p-1.5 pl-3 pr-2.5 shadow-sm text-xs font-bold text-brand-navy select-none">
            <Key className="w-3.5 h-3.5 text-brand-teal shrink-0" />
            <span className="text-[10px] text-brand-navy/50 font-extrabold uppercase">Key:</span>
            <span className="font-mono text-brand-navy tracking-tight">
              {showToken ? sessionToken : '••••••••••••••••••••'}
            </span>
            <button
              onClick={() => setShowToken(!showToken)}
              className="p-1 hover:bg-brand-beige rounded text-brand-navy/40 hover:text-brand-navy transition-colors cursor-pointer"
              title={showToken ? 'Hide key' : 'Show key'}
            >
              {showToken ? <EyeOff className="w-3.5 h-3.5" /> : <Eye className="w-3.5 h-3.5" />}
            </button>
            <button
              onClick={copyToClipboard}
              className="p-1 hover:bg-brand-beige rounded text-brand-navy/40 hover:text-brand-navy transition-colors cursor-pointer"
              title="Copy to Clipboard"
            >
              {copiedToken ? <Check className="w-3.5 h-3.5 text-brand-teal" /> : <Copy className="w-3.5 h-3.5" />}
            </button>
          </div>

          <div className="px-4 py-2.5 rounded-xl bg-brand-beige text-xs font-bold text-brand-navy border border-brand-navy/10 flex items-center gap-2 shadow-sm">
            <span
              className={`w-2.5 h-2.5 rounded-full ${
                currentStatus === 'READY'
                  ? 'bg-brand-teal animate-pulse'
                  : currentStatus === 'PROCESSING'
                  ? 'bg-brand-peach animate-spin'
                  : 'bg-brand-navy/40'
              }`}
            ></span>
            Pipeline Status:{' '}
            <span className={`uppercase font-extrabold ${currentStatus === 'READY' ? 'text-brand-teal' : currentStatus === 'PROCESSING' ? 'text-brand-peach' : 'text-brand-navy/40'}`}>
              {currentStatus === 'PROCESSING' 
                ? 'Processing Data...' 
                : currentStatus === 'READY' 
                ? 'Active' 
                : 'Awaiting Upload'}
            </span>
          </div>

          {readyPlatforms.length > 0 && (
            <button
              onClick={() => setShowUploadZone(!showUploadZone)}
              className={`px-4 py-2.5 rounded-xl border transition-all text-xs font-bold flex items-center gap-2 duration-150 cursor-pointer ${
                showUploadZone 
                  ? 'bg-brand-navy text-white border-brand-navy shadow-md'
                  : 'border-brand-teal/30 hover:border-brand-teal/60 bg-brand-teal/10 text-brand-navy hover:shadow-md'
              }`}
            >
              <UploadCloud className={`w-3.5 h-3.5 ${showUploadZone ? 'text-white' : 'text-brand-teal'}`} />
              {showUploadZone ? 'Hide Upload Panel' : 'Upload Zip File'}
            </button>
          )}

          {readyPlatforms.length > 0 && (
            <button
              onClick={handleResetPipeline}
              className="px-4 py-2.5 rounded-xl border border-brand-peach/30 hover:border-brand-peach/60 bg-brand-peach/10 text-brand-navy text-xs font-bold transition-all hover:shadow-md flex items-center gap-2 duration-150 cursor-pointer"
            >
              <RefreshCw className="w-3.5 h-3.5 text-brand-peach" />
              Reset Console
            </button>
          )}

          <button
            onClick={handleLogout}
            className="px-4 py-2.5 rounded-xl border border-brand-navy/15 hover:bg-brand-peach/10 hover:border-brand-peach/30 text-brand-navy text-xs font-bold transition-all flex items-center gap-2 duration-150 cursor-pointer"
            title="Disconnect Console"
          >
            <LogOut className="w-3.5 h-3.5 text-brand-peach" />
            Log Out
          </button>
        </div>
      </div>

      {/* View Switcher Sub-Navigation Tabs */}
      <div className="mb-8 border-b border-brand-navy/10 flex gap-4 text-left font-sans">
        <a 
          href="/dashboard"
          className="px-4 py-3 text-sm font-bold border-b-2 border-transparent text-brand-navy/50 hover:text-brand-navy transition-all"
          id="tab-personal-insights"
        >
          Personal Insights
        </a>
        <a 
          href="/population"
          className="px-4 py-3 text-sm font-bold border-b-2 border-transparent text-brand-navy/50 hover:text-brand-navy transition-all"
          id="tab-population-benchmark"
        >
          Population Benchmark
        </a>
        <a 
          href="/risk"
          className="px-4 py-3 text-sm font-extrabold border-b-2 border-brand-teal text-brand-teal transition-all"
          id="tab-mental-health-risk"
        >
          Mental Health Risk
        </a>
      </div>

      {showUploadZone && readyPlatforms.length > 0 && (
        <div className="bg-brand-beige/30 border border-brand-navy/10 rounded-3xl p-6 mb-8 animate-fade-in relative overflow-hidden text-left">
          <div className="absolute top-0 left-0 right-0 h-1 bg-brand-teal"></div>
          <div className="flex justify-between items-center mb-4">
            <div>
              <h3 className="font-bold text-brand-navy text-sm">Ingest Additional Platform History</h3>
              <p className="text-[10px] text-brand-navy/50">Upload a zip export to automatically extract, authorize, and integrate a new data source.</p>
            </div>
            <button 
              onClick={() => setShowUploadZone(false)}
              className="text-xs font-bold text-brand-peach hover:underline cursor-pointer"
            >
              Close Panel
            </button>
          </div>
          <UploadZone sessionToken={sessionToken} onUploadComplete={handleUploadComplete} />
        </div>
      )}

      {/* State 1: Upload Needed */}
      {readyPlatforms.length === 0 && currentStatus !== 'PROCESSING' && (
        <div className="space-y-12">
          <UploadZone sessionToken={sessionToken} onSessionGenerated={handleSessionGenerated} onUploadComplete={handleUploadComplete} />
          <div className="border border-brand-navy/10 rounded-3xl p-8 bg-brand-beige/20 text-center max-w-xl mx-auto space-y-3">
            <Database className="w-8 h-8 text-brand-navy/30 mx-auto" />
            <h3 className="font-bold text-brand-navy text-sm">Awaiting Ingress Stream</h3>
            <p className="text-xs text-brand-navy/60 leading-relaxed">
              Upon file ingestion, our wellness assessment will compile habit trend timelines.
            </p>
          </div>
        </div>
      )}

      {/* State 2: Processing Ingest */}
      {readyPlatforms.length === 0 && currentStatus === 'PROCESSING' && (
        <div className="bg-brand-beige border border-brand-navy/15 rounded-3xl p-12 text-center max-w-2xl mx-auto shadow-sm space-y-6">
          <div className="w-16 h-16 rounded-full bg-white flex items-center justify-center mx-auto shadow-sm text-brand-teal border border-brand-navy/10">
            <RefreshCw className="w-8 h-8 animate-spin" />
          </div>
          <div>
            <h2 className="text-xl font-bold text-brand-navy">
              {importStatusData?.status === 'queued' ? 'Worker Queueing Import...' : 'Extracting and Normalizing Takeout...'}
            </h2>
            <p className="text-xs text-brand-navy/60 mt-2 max-w-md mx-auto leading-relaxed">
              Our background ingestion worker is processing your YouTube archive. This will align daily logs and compile parameters.
            </p>
          </div>
        </div>
      )}

      {/* State 3: Risk Assessment Active */}
      {readyPlatforms.length > 0 && (
        <div className="space-y-6 text-left">
          
          {/* Medical Disclaimer Banner */}
          <div className="bg-amber-50 border border-amber-200 rounded-3xl p-5 text-amber-900 text-xs leading-relaxed flex gap-3 relative overflow-hidden">
            <div className="absolute left-0 top-0 bottom-0 w-1 bg-amber-500"></div>
            <Info className="w-5 h-5 text-amber-600 shrink-0 mt-0.5" />
            <div>
              <span className="font-extrabold uppercase tracking-wider text-[10px] block mb-1 text-amber-800">Self-Reflection & Personal Interest Disclaimer</span>
              This section is for personal interest, self-reflection, and informational purposes only. It is calculated to the best of our knowledge based on public research correlations. <strong>This does not constitute medical advice or a clinical diagnosis.</strong> If you are experiencing distress, anxiety, low mood, or any other health concerns, please consult a trained healthcare professional for expert advice.
            </div>
          </div>

          {/* Empty Live warning if user runs live mode but database query returns empty */}
          {!IS_MOCK_MODE && riskAnalysisResult?.isEmptyLive && (
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
                  Self-Reflection Wellness Model {IS_MOCK_MODE && '(Simulated)'}
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
                {isDetailedLoading && !IS_MOCK_MODE ? (
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
                {isDetailedLoading && !IS_MOCK_MODE ? (
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
                  {IS_MOCK_MODE ? 'Simulated Data' : 'YouTube Logs'}
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
                Metrics calculated over current selected range.
              </div>
            </div>

          </div>

          {/* Timeline Chart Box */}
          {!IS_MOCK_MODE && detailedError ? (
            <div className="bg-brand-peach/10 border border-brand-peach/30 rounded-3xl p-6 text-center text-brand-navy flex flex-col items-center gap-3">
              <ShieldAlert className="w-10 h-10 text-brand-peach" />
              <h4 className="font-bold">Failed to load wellness timeline data</h4>
              <p className="text-xs text-brand-navy/70">An error occurred while running the wellness timeline query.</p>
            </div>
          ) : !IS_MOCK_MODE && isDetailedLoading ? (
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
                    {['1D', '7D', '15D', '30D', '1Y', '5Y', 'all'].map((preset) => (
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
                    <span className="text-[9px] text-brand-navy/40 block">Queries backend to update chart scope.</span>
                  </div>
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
                    <a href="https://doi.org/10.1001/jamapsypchiatry.2019.2325" target="_blank" rel="noopener noreferrer" className="text-[10px] text-brand-teal hover:underline block font-semibold">
                      https://doi.org/10.1001/jamapsypchiatry.2019.2325
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
      )}
    </div>
  );
}

export default function RiskDashboardContainer() {
  return (
    <QueryClientProvider client={queryClient}>
      <RiskDashboardContent />
    </QueryClientProvider>
  );
}
