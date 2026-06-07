import React, { useState, useEffect, useMemo } from 'react';
import { QueryClient, QueryClientProvider, useQuery, useQueryClient } from '@tanstack/react-query';
import { 
  RefreshCw, Users, Database, ShieldAlert, UploadCloud,
  Key, Copy, Check, LogOut, Eye, EyeOff, ShieldCheck, Lock,
  TrendingUp, Activity, Calendar, Filter, Layers, CheckSquare, Square,
  ChevronDown, ChevronUp, Clock, Info
} from 'lucide-react';
import { 
  AreaChart, Area, XAxis, YAxis, Tooltip, ResponsiveContainer, 
  ReferenceLine, ComposedChart, Line, Legend, CartesianGrid,
  BarChart, Bar, Cell
} from 'recharts';
import UploadZone from './UploadZone';
import { usePopulationData } from '../hooks/usePopulationData';

const IS_MOCK_MODE = import.meta.env.PUBLIC_MOCK_API === 'true';


const queryClient = new QueryClient({
  defaultOptions: {
    queries: {
      refetchOnWindowFocus: false,
      retry: 1,
    },
  },
});

const ALL_PLATFORMS = ['YouTube', 'Instagram', 'TikTok', 'Spotify', 'Twitter', 'LinkedIn'];

const PLATFORM_COLORS: Record<string, string> = {
  youtube: '#537D96',   // brand-navy
  instagram: '#EC8F8D', // brand-peach
  tiktok: '#44A194',    // brand-teal
  spotify: '#5EAF81',   // brand-green
  twitter: '#8ba6b8',
  linkedin: '#66b8ad',
};

const REFERENCE_DATE = '2026-06-06';

function PopulationDashboardContent() {
  const queryClient = useQueryClient();
  const [showUploadZone, setShowUploadZone] = useState(false);
  const [useSyntheticData, setUseSyntheticData] = useState(true);
  
  // Custom Percentile Line parameters
  const [showCustomPercentile, setShowCustomPercentile] = useState(false);
  const [customPercentile, setCustomPercentile] = useState(90);

  // Timeframe and SMA filters matching MainTimeline
  const [startDate, setStartDate] = useState('2026-05-08');
  const [endDate, setEndDate] = useState('2026-06-06');
  const [trendlinePeriod, setTrendlinePeriod] = useState(7);
  const [showSMA, setShowSMA] = useState(true);
  const [showAdvancedFilters, setShowAdvancedFilters] = useState(false);
  const [activePlatforms, setActivePlatforms] = useState<string[]>(['youtube']);
  const [currentImportId, setCurrentImportId] = useState<string | null>(null);

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
    setSessionToken(null);
    setLoginIdInput('');
    queryClient.clear(); // Clear TanStack Query cache
  };

  const copyToClipboard = () => {
    if (sessionToken) {
      navigator.clipboard.writeText(sessionToken);
      setCopiedToken(true);
      setTimeout(() => setCopiedToken(false), 2000);
    }
  };

  // Session Probe Query: check if youtube_usage data is ready on mount/login
  const { data: probeData, refetch: refetchProbe } = useQuery({
    queryKey: ['probe', sessionToken],
    queryFn: async () => {
      if (!sessionToken) return null;
      const res = await fetch(`/api/query`, {
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
            start_date: '2026-05-08',
            end_date: '2026-06-06',
          },
          options: {
            limit: 1
          }
        })
      });
      if (!res.ok) return { rows: [] };
      return res.json();
    },
    enabled: !!sessionToken && !currentImportId,
  });

  // Import Polling Query: polls imports/{currentImportId} when active
  const { data: importStatusData } = useQuery({
    queryKey: ['importStatus', currentImportId, sessionToken],
    queryFn: async () => {
      const res = await fetch(`/api/imports/${currentImportId}`, {
        headers: {
          'Authorization': `Bearer ${sessionToken}`
        }
      });
      if (!res.ok) throw new Error('Import status query failed');
      return res.json();
    },
    enabled: !!currentImportId && !!sessionToken,
    refetchInterval: (query) => {
      const status = query.state.data?.status;
      return (status === 'queued' || status === 'running') ? 1000 : false;
    },
  });

  // Effect to resolve queue progress and update probe results
  useEffect(() => {
    if (importStatusData?.status === 'completed') {
      refetchProbe();
      setCurrentImportId(null);
    }
  }, [importStatusData?.status, refetchProbe]);

  const currentStatus = currentImportId 
    ? 'PROCESSING' 
    : (probeData?.rows && probeData.rows.length > 0 ? 'READY' : 'NOT_UPLOADED');

  const paddedStartDate = useMemo(() => {
    if (!startDate) return '';
    const dateObj = new Date(startDate);
    dateObj.setDate(dateObj.getDate() - 90);
    return dateObj.toISOString().split('T')[0];
  }, [startDate]);

  const readyPlatforms = React.useMemo(() => {
    if (IS_MOCK_MODE) return ['youtube', 'instagram', 'tiktok', 'spotify'];
    return currentStatus === 'READY' ? ['youtube'] : [];
  }, [IS_MOCK_MODE, currentStatus]);

  // Fetch Population Analytics
  const {
    data: popData,
    isLoading: isPopLoading,
    error: popError,
    refetch: refetchPop
  } = usePopulationData(
    activePlatforms.filter(p => readyPlatforms.includes(p)),
    paddedStartDate, 
    endDate, 
    useSyntheticData, 
    customPercentile,
    readyPlatforms.length > 0 && activePlatforms.some(p => readyPlatforms.includes(p)), 
    sessionToken,
    startDate
  );

  const handleUploadComplete = async (s3Key: string, s3Bucket: string) => {
    try {
      const res = await fetch(`/api/imports`, {
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
      setCurrentImportId(data.import_id);
    } catch (err) {
      console.error('Error starting import:', err);
    }
  };

  // Reset pipeline state locally & on mock server
  const handleResetPipeline = async () => {
    try {
      await fetch('/api/upload-url'); // GET triggers state reset in mock backend
      setStartDate('2026-05-08');
      setEndDate('2026-06-06');
      setTrendlinePeriod(7);
      setShowSMA(true);
      setShowAdvancedFilters(false);
      setCustomPercentile(90);
      setShowCustomPercentile(false);
      
      // Wipe queries from cache
      queryClient.setQueryData(['probe', sessionToken], null);
      queryClient.setQueryData(['population'], null);
      setCurrentImportId(null);
      
      // Force status refetch to align
      queryClient.invalidateQueries({ queryKey: ['probe'] });
    } catch (err) {
      console.error('Failed to reset pipeline:', err);
    }
  };

  // Active preset matching MainTimeline
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

  // 1. Calculate dynamic smoothing window based on selected timeframe total days
  const totalDays = useMemo(() => {
    if (!popData?.deciles) return 0;
    return popData.deciles.length;
  }, [popData?.deciles]);

  const smoothWindow = useMemo(() => {
    return 1;                        // raw (no smoothing) by default
  }, []);

  // 2. Set moving average default to a multiple (2x) of the smoothing window when it changes
  useEffect(() => {
    const defaultMA = smoothWindow > 1 ? smoothWindow * 2 : 7;
    setTrendlinePeriod(defaultMA);
  }, [smoothWindow]);

  // 3. Smooth all curves in deciles timeline using the dynamic rolling average window
  const smoothedDeciles = useMemo(() => {
    if (!popData?.deciles) return [];
    if (smoothWindow <= 1) return popData.deciles;

    return popData.deciles.map((record, index) => {
      const start = Math.max(0, index - smoothWindow + 1);
      const count = index - start + 1;

      let userSum = 0;
      let medianSum = 0;
      let top10Sum = 0;
      let bottom10Sum = 0;
      let customPercentileSum = 0;

      for (let j = start; j <= index; j++) {
        userSum += popData.deciles[j].user;
        medianSum += popData.deciles[j].median;
        top10Sum += popData.deciles[j].top10;
        bottom10Sum += popData.deciles[j].bottom10;
        customPercentileSum += popData.deciles[j].customPercentileHours;
      }

      return {
        date: record.date,
        user: parseFloat((userSum / count).toFixed(2)),
        median: parseFloat((medianSum / count).toFixed(2)),
        top10: parseFloat((top10Sum / count).toFixed(2)),
        bottom10: parseFloat((bottom10Sum / count).toFixed(2)),
        customPercentileHours: parseFloat((customPercentileSum / count).toFixed(2)),
      };
    });
  }, [popData?.deciles, smoothWindow]);

  // 4. Compute User SMA Trendline over the smoothed curves
  const decilesWithSMA = useMemo(() => {
    if (smoothedDeciles.length === 0) return [];
    const allSMA = smoothedDeciles.map((record, index) => {
      let sum = 0;
      let count = 0;
      const start = Math.max(0, index - trendlinePeriod + 1);
      for (let i = start; i <= index; i++) {
        sum += smoothedDeciles[i].user;
        count++;
      }
      const smaHours = count > 0 ? parseFloat((sum / count).toFixed(2)) : 0;
      return {
        ...record,
        smaHours
      };
    });
    // Filter to keep only the visible dates
    return allSMA.filter(record => record.date >= startDate && record.date <= endDate);
  }, [smoothedDeciles, trendlinePeriod, startDate, endDate]);

  // 5. Group distribution data into 1-hour interval bins (0-24h)
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
    const userBinIdx = Math.min(23, Math.floor(userAvg));
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
  const hasPopulationData = IS_MOCK_MODE || (popData?.hasPopulationData === true);

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
    <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 py-10">
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
            <span className="uppercase text-brand-teal font-black">
              {currentStatus === 'PROCESSING' ? 'Processing Data...' : 'Active'}
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
      <div className="mb-8 border-b border-brand-navy/10 flex gap-4 text-left">
        <a 
          href="/dashboard"
          className="px-4 py-3 text-sm font-bold border-b-2 border-transparent text-brand-navy/50 hover:text-brand-navy transition-all"
          id="tab-personal-insights"
        >
          Personal Insights
        </a>
        <a 
          href="/population"
          className="px-4 py-3 text-sm font-extrabold border-b-2 border-brand-teal text-brand-teal transition-all"
          id="tab-population-benchmark"
        >
          Population Benchmark
        </a>
        <a 
          href="/risk"
          className="px-4 py-3 text-sm font-bold border-b-2 border-transparent text-brand-navy/50 hover:text-brand-navy transition-all"
          id="tab-mental-health-risk"
        >
          Mental Health Risk
        </a>
      </div>

      {/* Collapsible Upload Zone Drawer */}
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

      {/* State 1: Ingest Needed */}
      {readyPlatforms.length === 0 && currentStatus !== 'PROCESSING' && (
        <div className="space-y-12">
          <UploadZone sessionToken={sessionToken} onSessionGenerated={handleSessionGenerated} onUploadComplete={handleUploadComplete} />
          
          <div className="border border-brand-navy/10 rounded-3xl p-8 bg-brand-beige/20 text-center max-w-xl mx-auto space-y-3">
            <Database className="w-8 h-8 text-brand-navy/30 mx-auto" />
            <h3 className="font-bold text-brand-navy text-sm">Awaiting Ingress Stream</h3>
            <p className="text-xs text-brand-navy/60 leading-relaxed">
              Upon file ingestion, our analytics console will compile comparative benchmarks using population metrics.
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
              Our background ingestion worker is processing your YouTube archive. Comparative distribution matrices will build automatically.
            </p>
          </div>
        </div>
      )}

      {/* State 3: Population Dashboard Ready */}
      {readyPlatforms.length > 0 && (
        <div className="space-y-6 text-left">
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
                ) : !IS_MOCK_MODE && popData && hasPopulationData && popData.userDailyAverageHours !== null ? (
                  <>
                    <h2 className="text-2xl sm:text-3xl font-black tracking-tight leading-tight">
                      Your daily usage exceeds <span className="text-brand-peach">{popData.userPercentile}%</span> of the population
                    </h2>
                    <div className="inline-block px-2.5 py-0.5 text-[9px] font-extrabold uppercase tracking-wider rounded-md border border-white/20 bg-white/5 mt-1.5">
                      Real Database Mode · Population Comparison Active
                    </div>
                  </>
                ) : !IS_MOCK_MODE && popData && !hasPopulationData ? (
                  <>
                    <h2 className="text-2xl sm:text-3xl font-black tracking-tight leading-tight">
                      Your data is ready for analysis
                    </h2>
                    <div className="inline-block px-2.5 py-0.5 text-[9px] font-extrabold uppercase tracking-wider rounded-md border border-white/20 bg-white/5 mt-1.5">
                      Real Database Mode Active · Population API Pending
                    </div>
                  </>
                ) : percentileNuance ? (
                  <>
                    <h2 className="text-2xl sm:text-3xl font-black tracking-tight leading-tight">
                      {percentileNuance.title}
                    </h2>
                    <div className="inline-block px-2.5 py-0.5 text-[9px] font-extrabold uppercase tracking-wider rounded-md border border-white/20 bg-white/5 mt-1.5">
                      {percentileNuance.status}
                    </div>
                  </>
                ) : null}
                <p className="text-xs text-white/70 max-w-xl leading-relaxed pt-1">
                  {!IS_MOCK_MODE && !hasPopulationData
                    ? "Population comparison data is not yet available from the backend API. Once the endpoint is live, percentile rankings and cohort benchmarks will appear here automatically."
                    : !IS_MOCK_MODE && hasPopulationData
                    ? "Your percentile ranking and cohort benchmarks are sourced directly from the population database."
                    : (percentileNuance ? percentileNuance.description : "")}
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
            
            <div className="flex items-center gap-3 bg-brand-beige/20 border border-brand-navy/10 rounded-2xl p-2.5 px-4 select-none w-full sm:w-auto justify-between">
              <div>
                <span className="text-xs font-black text-brand-navy block">Synthetic Population Data</span>
                <span className="text-[9px] text-brand-navy/50 block -mt-0.5">Use large realistic curves vs small local dataset</span>
              </div>
              <button
                onClick={() => setUseSyntheticData(!useSyntheticData)}
                className={`relative inline-flex h-6 w-11 shrink-0 cursor-pointer rounded-full border-2 border-transparent transition-colors duration-200 ease-in-out focus:outline-none ${
                  useSyntheticData ? 'bg-brand-teal' : 'bg-brand-navy/20'
                }`}
                role="switch"
                aria-checked={useSyntheticData}
                id="toggle-synthetic-data"
                title="Toggle Synthetic Population Data"
              >
                <span
                  aria-hidden="true"
                  className={`pointer-events-none inline-block h-5 w-5 transform rounded-full bg-white shadow ring-0 transition duration-200 ease-in-out ${
                    useSyntheticData ? 'translate-x-5' : 'translate-x-0'
                  }`}
                />
              </button>
            </div>
          </div>

          {/* Timeline and Bell Curve Section */}
          {popError ? (
            <div className="bg-brand-peach/10 border border-brand-peach/30 rounded-3xl p-8 text-center text-brand-navy flex flex-col items-center gap-3">
              <ShieldAlert className="w-10 h-10 text-brand-peach" />
              <h4 className="font-bold">Failed to load comparative statistics</h4>
              <p className="text-xs text-brand-navy/70">An error occurred while building the population aggregates.</p>
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
                <div className="bg-white border border-brand-navy/10 rounded-3xl p-6 shadow-sm space-y-6">
                  
                  {/* Timeline Header Row (emulating MainTimeline controls) */}
                  <div className="flex flex-col xl:flex-row xl:items-center xl:justify-between gap-4 pb-4 border-b border-brand-navy/5">
                    <div className="flex items-center gap-3">
                      <div className="w-10 h-10 rounded-xl bg-brand-navy/5 flex items-center justify-center text-brand-navy">
                        <Layers className="w-5 h-5" />
                      </div>
                      <div>
                        <div className="flex items-center gap-2">
                          <h3 className="font-bold text-brand-navy text-lg">Population Cohort Timeline</h3>
                          {smoothWindow > 1 && (
                            <span className="text-[9px] bg-brand-teal/10 text-brand-teal px-2 py-0.5 rounded-full font-extrabold uppercase">
                              {smoothWindow}-Day Smoothed
                            </span>
                          )}
                        </div>
                        <p className="text-xs text-brand-navy/50">Your daily hours compared to Median and Top 10% ranges.</p>
                      </div>
                    </div>

                    <div className="flex flex-wrap items-center gap-3">
                      {/* Presets */}
                      <div className="flex items-center bg-brand-beige/60 p-1 rounded-xl border border-brand-navy/5 flex-wrap">
                        {['1D', '7D', '15D', '30D', '1Y', '5Y', 'all'].map((preset) => (
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

                      {/* SMA Toggle */}
                      <button
                        onClick={() => setShowSMA(!showSMA)}
                        className={`px-4 py-2 rounded-xl text-xs font-bold border transition-all flex items-center gap-2 cursor-pointer ${
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
                            min="2026-05-08"
                            max="2026-06-06"
                            onChange={(e) => setStartDate(e.target.value)}
                            className="bg-white border border-brand-navy/15 rounded-xl px-3 py-2 text-xs font-bold text-brand-navy focus:outline-none focus:ring-1 focus:ring-brand-teal w-full"
                          />
                          <span className="text-brand-navy/40 text-xs font-bold">to</span>
                          <input
                            type="date"
                            value={endDate}
                            min="2026-05-08"
                            max="2026-06-06"
                            onChange={(e) => setEndDate(e.target.value)}
                            className="bg-white border border-brand-navy/15 rounded-xl px-3 py-2 text-xs font-bold text-brand-navy focus:outline-none focus:ring-1 focus:ring-brand-teal w-full"
                          />
                        </div>
                      </div>

                      {/* 2. Moving Average SMA Period slider */}
                      <div className="space-y-2">
                        <label className="text-[10px] uppercase tracking-wider font-extrabold text-brand-navy/60 flex items-center gap-1.5">
                          <span className="w-2.5 h-2.5 rounded-full bg-brand-peach"></span>
                          Moving Average (SMA) Period
                        </label>
                        <div className="flex items-center gap-3">
                          <input
                            type="number"
                            min="1"
                            max="120"
                            value={trendlinePeriod}
                            onChange={(e) => setTrendlinePeriod(Math.max(1, parseInt(e.target.value) || 7))}
                            className="bg-white border border-brand-navy/15 rounded-xl px-3 py-2 text-xs font-bold text-brand-navy focus:outline-none w-20 text-center"
                          />
                          <span className="text-xs font-bold text-brand-navy/70">Days</span>
                        </div>
                      </div>

                      {/* 3. Custom Percentile Line Controls */}
                      {IS_MOCK_MODE && (
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
                          data={decilesWithSMA}
                          margin={{ top: 10, right: 15, left: -20, bottom: 0 }}
                        >
                          <CartesianGrid strokeDasharray="3 3" stroke="#537D96" strokeOpacity={0.07} />
                          <XAxis 
                            dataKey="date" 
                            tickFormatter={(str) => {
                              const parts = str.split('-');
                              if (parts.length === 3) {
                                const dateObj = new Date(str);
                                const diffDays = decilesWithSMA.length;
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
                            formatter={(value: any, name: string) => {
                              if (value === null || value === undefined) return null;
                              if (name === 'user') return [`${value} hrs`, 'Your Watch Hours'];
                              if (name === 'median') return [`${value} hrs`, 'Population Median (50th)'];
                              if (name === 'top10') return [`${value} hrs`, 'Top 10% Power Users'];
                              if (name === 'bottom10') return [`${value} hrs`, 'Bottom 10% Users'];
                              if (name === 'customPercentileHours') return [`${value} hrs`, `Custom ${customPercentile}th Percentile`];
                              if (name === 'smaHours') return [`${value} hrs`, `${trendlinePeriod}-Day SMA`];
                              return [`${value} hrs`, name];
                            }}
                          />
                          
                          {/* Shaded Areas representing Cohort Bands (Mock mode only) */}
                          {IS_MOCK_MODE && (
                            <>
                              <Area 
                                name="top10" 
                                type="monotone" 
                                dataKey="top10" 
                                fill="#44A194" 
                                fillOpacity={0.06} 
                                stroke="transparent" 
                              />
                              <Area 
                                name="median" 
                                type="monotone" 
                                dataKey="median" 
                                fill="#537D96" 
                                fillOpacity={0.09} 
                                stroke="transparent" 
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

                          {/* Dashed line representing custom percentile if toggled (Mock mode only) */}
                          {IS_MOCK_MODE && showCustomPercentile && (
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

                          {/* Dynamic SMA Trendline of User's hours */}
                          {showSMA && (
                            <Line
                              name="smaHours"
                              type="monotone"
                              dataKey="smaHours"
                              stroke="#537D96"
                              strokeWidth={2}
                              strokeDasharray="3 3"
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
                      {IS_MOCK_MODE && (
                        <div className="flex items-center gap-1.5">
                          <span className="w-3.5 h-3.5 bg-brand-navy/15 rounded"></span>
                          <span>Median Cohort Shading</span>
                        </div>
                      )}
                      {IS_MOCK_MODE && showCustomPercentile && (
                        <div className="flex items-center gap-1.5">
                          <span className="w-3.5 h-1 border-t-2 border-dashed border-brand-teal"></span>
                          <span>{customPercentile}th Percentile Benchmark</span>
                        </div>
                      )}
                      {showSMA && (
                        <div className="flex items-center gap-1.5">
                          <span className="w-3.5 h-1 border-t-2 border-dashed border-brand-navy"></span>
                          <span>{trendlinePeriod}-Day SMA (Trendline)</span>
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
                  {!IS_MOCK_MODE && !hasPopulationData ? (
                    <div className="text-center p-6 space-y-3 max-w-xs bg-brand-beige/10 rounded-2xl border border-brand-navy/5">
                      <TrendingUp className="w-8 h-8 text-brand-navy/40 mx-auto" />
                      <p className="text-xs font-bold text-brand-navy">Population distribution unavailable</p>
                      <p className="text-[10px] text-brand-navy/50 leading-relaxed">The population comparison API is not yet available. This chart will populate automatically once the endpoint is live.</p>
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
                                      {popData.useSyntheticData ? `${data.density} active users` : `${data.density} actual user(s)`}
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
            <div className="bg-white border border-brand-navy/10 rounded-3xl p-6 shadow-sm space-y-6">
              
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
                  <p className="text-sm font-bold text-brand-navy">Population comparison pending</p>
                  <p className="text-xs text-brand-navy/50 leading-relaxed">Hour-by-hour divergence analysis will appear here once the population benchmark API is live. Your own usage data is already being tracked.</p>
                </div>
              ) : (
                <div className="space-y-4">
                  <div className="grid grid-cols-4 sm:grid-cols-6 md:grid-cols-8 lg:grid-cols-12 gap-3">
                    {popData.hourlyAverages.map((row) => {
                    const userHrs = row.userAvg;
                    const popHrs = row.populationAvg;
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
      )}
    </div>
  );
}

export default function PopulationDashboardContainer() {
  return (
    <QueryClientProvider client={queryClient}>
      <PopulationDashboardContent />
    </QueryClientProvider>
  );
}
