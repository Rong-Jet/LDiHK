import React, { useState, useEffect } from 'react';
import { QueryClient, QueryClientProvider, useQuery, useQueryClient } from '@tanstack/react-query';
import { 
  RefreshCw, BarChart3, Database, ShieldAlert, UploadCloud,
  Key, Copy, Check, LogOut, Eye, EyeOff, ShieldCheck, Lock
} from 'lucide-react';
import UploadZone from './UploadZone';
import MainTimeline from './MainTimeline';
import DeepDive from './DeepDive';
import BehavioralHeatmap from './BehavioralHeatmap';
import { useAnalyticsData } from '../hooks/useAnalyticsData';
import { apiRoutes, authHeaders, isMockApiMode, jsonHeaders } from '../lib/api';

const queryClient = new QueryClient({
  defaultOptions: {
    queries: {
      refetchOnWindowFocus: false,
      retry: 1,
    },
  },
});

const isPendingEnrichment = (importStatus: any) => (
  importStatus?.status === 'completed'
  && (importStatus?.enrichment_status === 'queued' || importStatus?.enrichment_status === 'running')
);

const isResolvedImportStatus = (importStatus: any) => (
  importStatus?.status === 'failed'
  || (importStatus?.status === 'completed' && !isPendingEnrichment(importStatus))
);

const shouldPollImportStatus = (importStatus: any) => (
  importStatus?.status === 'queued'
  || importStatus?.status === 'running'
  || isPendingEnrichment(importStatus)
);

function DashboardContent() {
  const queryClient = useQueryClient();
  const [uploadCompleted, setUploadCompleted] = useState(false);
  const [selectedDate, setSelectedDate] = useState<string | null>(null);
  const [showUploadZone, setShowUploadZone] = useState(false);
  
  const [sessionToken, setSessionToken] = useState<string | null>(() => {
    if (typeof window !== 'undefined') {
      return localStorage.getItem('ldihk_session_token') || null;
    }
    return null;
  });
  const [currentImportId, setCurrentImportId] = useState<string | null>(() => {
    if (typeof window !== 'undefined') {
      return localStorage.getItem('ldihk_current_import_id') || null;
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
    setUploadCompleted(false);
    setSelectedDate(null);
    setCurrentImportId(null);
    queryClient.clear(); // Clear TanStack Query cache
  };

  const copyToClipboard = () => {
    if (sessionToken) {
      navigator.clipboard.writeText(sessionToken);
      setCopiedToken(true);
      setTimeout(() => setCopiedToken(false), 2000);
    }
  };

  const [activePlatforms, setActivePlatforms] = useState<string[]>(['youtube']);

  // Date Range Scope (defaults to past 30 days relative to 2026-06-06 reference date)
  const [startDate, setStartDate] = useState('2026-05-08');
  const [endDate, setEndDate] = useState('2026-06-06');

  // Session Probe Query: check if youtube_usage data is ready on mount/login
  const { data: probeData, refetch: refetchProbe } = useQuery({
    queryKey: ['probe', sessionToken],
    queryFn: async () => {
      if (!sessionToken) return null;
      const res = await fetch(apiRoutes.query(), {
        method: 'POST',
        headers: {
          ...jsonHeaders,
          ...authHeaders(sessionToken),
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
    enabled: !!sessionToken && !currentImportId,
  });

  // Import Polling Query: polls imports/{currentImportId} when active
  const { data: importStatusData } = useQuery({
    queryKey: ['importStatus', currentImportId, sessionToken],
    queryFn: async () => {
      const res = await fetch(apiRoutes.importStatus(currentImportId || ''), {
        headers: {
          ...authHeaders(sessionToken),
        }
      });
      if (!res.ok) throw new Error('Import status query failed');
      return res.json();
    },
    enabled: !!currentImportId && !!sessionToken,
    refetchInterval: (query) => {
      return shouldPollImportStatus(query.state.data) ? 1000 : false;
    },
  });

  // Effect to resolve queue progress and update probe results
  useEffect(() => {
    if (isResolvedImportStatus(importStatusData)) {
      localStorage.removeItem('ldihk_current_import_id');
      queryClient.invalidateQueries({ queryKey: ['insights'] });
      refetchProbe();
      setCurrentImportId(null);
    }
  }, [
    importStatusData?.status,
    importStatusData?.enrichment_status,
    queryClient,
    refetchProbe,
  ]);

  const isPipelineProcessing = currentImportId && !isResolvedImportStatus(importStatusData);
  const currentStatus = isPipelineProcessing
    ? 'PROCESSING' 
    : (probeData?.rows && probeData.rows.length > 0 ? 'READY' : 'NOT_UPLOADED');
  const processingTitle = importStatusData?.status === 'queued'
    ? 'Worker Queueing Import...'
    : isPendingEnrichment(importStatusData)
      ? 'Enriching Video Durations...'
      : 'Extracting and Normalizing Takeout...';
  const processingDescription = isPendingEnrichment(importStatusData)
    ? 'The archive import is complete. The duration worker is fetching video metadata before final analytics are shown.'
    : 'Our background ingestion worker is processing your YouTube archive. This will flatten daily history logs, map hourly watch boundaries, and build timeline analytics.';
  const recordsSeen = importStatusData?.records_seen || 0;
  const recordsImported = importStatusData?.records_imported || 0;
  const progressPercent = importStatusData?.status === 'queued'
    ? 10
    : isPendingEnrichment(importStatusData)
      ? 95
      : recordsSeen > 0
        ? Math.min(95, (recordsImported / recordsSeen) * 100)
        : 20;

  // Discovered Date Bounds
  const discoveredBounds = React.useMemo(() => {
    if (!probeData?.rows || probeData.rows.length === 0) {
      return { minDate: '2026-05-08', maxDate: '2026-06-06' };
    }
    const dates = probeData.rows.map((r: any) => r.date).sort();
    return {
      minDate: dates[0],
      maxDate: dates[dates.length - 1],
    };
  }, [probeData]);

  const datasets = React.useMemo(() => {
    const statusVal = isMockApiMode ? 'READY' : currentStatus;
    const bounds = discoveredBounds;
    return {
      youtube: {
        status: statusVal,
        min_date: bounds.minDate,
        max_date: bounds.maxDate,
      },
      instagram: {
        status: statusVal,
        min_date: bounds.minDate,
        max_date: bounds.maxDate,
      },
      tiktok: {
        status: statusVal,
        min_date: bounds.minDate,
        max_date: bounds.maxDate,
      },
      spotify: {
        status: statusVal,
        min_date: bounds.minDate,
        max_date: bounds.maxDate,
      }
    };
  }, [currentStatus, discoveredBounds]);

  // Derive global min/max date bounds across all ready platforms
  const dateBounds = React.useMemo(() => {
    return discoveredBounds;
  }, [discoveredBounds]);

  // Filter which platforms are actually uploaded and ready to query
  const readyPlatforms = React.useMemo(() => {
    if (isMockApiMode) return ['youtube', 'instagram', 'tiktok', 'spotify'];
    return currentStatus === 'READY' ? ['youtube'] : [];
  }, [currentStatus]);

  // Only query active platforms that are actually ready
  const platformsToQuery = React.useMemo(() => {
    return activePlatforms.filter((p) => readyPlatforms.includes(p));
  }, [activePlatforms, readyPlatforms]);

  // Automatically update start and end dates when date bounds are discovered
  React.useEffect(() => {
    if (dateBounds.minDate && dateBounds.maxDate) {
      const [y, m, d] = dateBounds.maxDate.split('-').map(Number);
      const maxDateObj = new Date(Date.UTC(y, m - 1, d));
      const minDateObj = new Date(dateBounds.minDate);
      const diffDays = Math.round((maxDateObj.getTime() - minDateObj.getTime()) / (1000 * 3600 * 24));

      if (diffDays > 90) {
        // Set visible window to the last 30 days of the dataset
        const defaultStart = new Date(maxDateObj);
        defaultStart.setUTCDate(defaultStart.getUTCDate() - 29);
        setStartDate(defaultStart.toISOString().split('T')[0]);
        setEndDate(dateBounds.maxDate);
      } else {
        setStartDate(dateBounds.minDate);
        setEndDate(dateBounds.maxDate);
      }
    }
  }, [dateBounds.minDate, dateBounds.maxDate]);

  // Analytics Ingest Query
  const { 
    chartData, 
    hourlyHeatmapData, 
    totalScopeHours = 0,
    dayCount = 1,
    isLoading: isInsightsLoading, 
    error: insightsError, 
    refetch: refetchInsights 
  } = useAnalyticsData(platformsToQuery, startDate, endDate, readyPlatforms.length > 0, sessionToken);

  const handleUploadComplete = async (s3Key: string, s3Bucket: string, activeSessionToken: string) => {
    try {
      const res = await fetch(apiRoutes.imports(), {
        method: 'POST',
        headers: {
          ...jsonHeaders,
          ...authHeaders(activeSessionToken),
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
      throw err;
    }
  };

  // Reset pipeline state locally & on mock server
  const handleResetPipeline = async () => {
    try {
      await fetch(apiRoutes.uploadUrl()); // GET triggers state reset in mock backend
      setUploadCompleted(false);
      setSelectedDate(null);
      setStartDate('2026-05-08');
      setEndDate('2026-06-06');
      
      // Wipe queries from cache
      queryClient.setQueryData(['probe', sessionToken], null);
      queryClient.setQueryData(['insights'], null);
      localStorage.removeItem('ldihk_current_import_id');
      setCurrentImportId(null);
      
      // Force status refetch to align
      queryClient.invalidateQueries({ queryKey: ['probe'] });
    } catch (err) {
      console.error('Failed to reset pipeline:', err);
    }
  };

  // Find dataset record for selected date
  const selectedDayData = React.useMemo(() => {
    if (!selectedDate) return undefined;
    return chartData.find((d) => d.date === selectedDate);
  }, [chartData, selectedDate]);

  if (!sessionToken) {
    return (
      <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 py-10 text-left">
        {/* Subheader */}
        <div className="mb-10 pb-6 border-b border-brand-navy/10">
          <h1 className="text-3xl font-extrabold text-brand-navy tracking-tight">Analytics Console</h1>
          <p className="text-sm text-brand-navy/60 mt-1">Manage, process, and query your social media data pipelines.</p>
        </div>

        {/* Glassmorphic Auth Panel */}
        <div className="bg-white border border-brand-navy/15 rounded-[32px] overflow-hidden shadow-2xl relative">
          <div className="absolute top-0 left-0 right-0 h-1.5 bg-gradient-to-r from-brand-teal via-brand-peach to-brand-teal"></div>
          
          <div className="grid grid-cols-1 md:grid-cols-2">
            {/* Left Column: Login */}
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

              {/* Login Form (triggers browser save/autofill) */}
              <form onSubmit={handleLoginSubmit} className="space-y-4">
                {/* Hidden username field for password managers */}
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

            {/* Right Column: New Workspace / Upload */}
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

              {/* Upload Zone */}
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
      <div className="mb-10 flex flex-col md:flex-row md:items-center md:justify-between gap-6 pb-6 border-b border-brand-navy/10 text-left">
        <div>
          <h1 className="text-3xl font-extrabold text-brand-navy tracking-tight">Analytics Console</h1>
          <p className="text-sm text-brand-navy/60 mt-1">Manage, process, and query your social media data pipelines.</p>
        </div>

        <div className="flex flex-wrap items-center gap-3">
          {/* LDiHK-ID Display */}
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

          {/* Global Status Pill */}
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

          {/* Ingest Data Toggle Button */}
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

          {/* Reset Action */}
          {readyPlatforms.length > 0 && (
            <button
              onClick={handleResetPipeline}
              className="px-4 py-2.5 rounded-xl border border-brand-peach/30 hover:border-brand-peach/60 bg-brand-peach/10 text-brand-navy text-xs font-bold transition-all hover:shadow-md flex items-center gap-2 duration-150 cursor-pointer"
            >
              <RefreshCw className="w-3.5 h-3.5 text-brand-peach" />
              Reset Console
            </button>
          )}

          {/* Log Out button */}
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
          className="px-4 py-3 text-sm font-extrabold border-b-2 border-brand-teal text-brand-teal transition-all"
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
          className="px-4 py-3 text-sm font-bold border-b-2 border-transparent text-brand-navy/50 hover:text-brand-navy transition-all"
          id="tab-mental-health-risk"
        >
          Mental Health Risk
        </a>
      </div>

      {/* Collapsible Upload Zone Drawer */}
      {showUploadZone && readyPlatforms.length > 0 && (
        <div className="bg-brand-beige/30 border border-brand-navy/10 rounded-3xl p-6 mb-8 animate-fade-in relative overflow-hidden">
          <div className="absolute top-0 left-0 right-0 h-1 bg-brand-teal"></div>
          <div className="flex justify-between items-center mb-4 text-left">
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

      {/* State 1: Upload Needed (Only if no datasets are ready) */}
      {readyPlatforms.length === 0 && currentStatus !== 'PROCESSING' && (
        <div className="space-y-12">
          <UploadZone sessionToken={sessionToken} onSessionGenerated={handleSessionGenerated} onUploadComplete={handleUploadComplete} />
          
          {/* Visual Scaffolding Placeholders */}
          <div className="border border-brand-navy/10 rounded-3xl p-8 bg-brand-beige/20 text-center max-w-xl mx-auto space-y-3">
            <Database className="w-8 h-8 text-brand-navy/30 mx-auto" />
            <h3 className="font-bold text-brand-navy text-sm">Awaiting Ingress Stream</h3>
            <p className="text-xs text-brand-navy/60 leading-relaxed">
              Upon file ingestion, our analytics console will poll the indexing service to normalize raw segments into timeline parameters.
            </p>
          </div>
        </div>
      )}

      {/* State 2: Upload completed, but server is processing (Only if no datasets are ready) */}
      {readyPlatforms.length === 0 && currentStatus === 'PROCESSING' && (
        <div className="bg-brand-beige border border-brand-navy/15 rounded-3xl p-12 text-center max-w-2xl mx-auto shadow-sm space-y-6">
          <div className="w-16 h-16 rounded-full bg-white flex items-center justify-center mx-auto shadow-sm text-brand-teal border border-brand-navy/10">
            <RefreshCw className="w-8 h-8 animate-spin" />
          </div>
          <div>
            <h2 className="text-xl font-bold text-brand-navy">
              {processingTitle}
            </h2>
            <p className="text-xs text-brand-navy/60 mt-2 max-w-md mx-auto leading-relaxed">
              {processingDescription}
            </p>
          </div>

          <div className="grid grid-cols-3 gap-4 bg-white/50 p-4 rounded-2xl border border-brand-navy/5 max-w-md mx-auto text-left">
            <div>
              <span className="text-[9px] uppercase tracking-wider font-extrabold text-brand-navy/50 block">Status</span>
              <span className="text-xs font-black text-brand-teal capitalize">
                {isPendingEnrichment(importStatusData) ? 'enriching' : importStatusData?.status || 'queued'}
              </span>
            </div>
            <div>
              <span className="text-[9px] uppercase tracking-wider font-extrabold text-brand-navy/50 block">Records Ingested</span>
              <span className="text-xs font-black text-brand-navy">
                {recordsImported} / {recordsSeen}
              </span>
            </div>
            <div>
              <span className="text-[9px] uppercase tracking-wider font-extrabold text-brand-navy/50 block">Warnings</span>
              <span className="text-xs font-black text-brand-peach">
                {importStatusData?.warnings_count || 0}
              </span>
            </div>
          </div>

          <div className="max-w-xs mx-auto space-y-2 pt-2">
            <div className="flex justify-between text-[10px] font-bold text-brand-navy/60">
              <span>Database Sync</span>
              <span>Polling worker status...</span>
            </div>
            <div className="w-full bg-brand-navy/10 h-1.5 rounded-full overflow-hidden">
              <div 
                className="bg-brand-teal h-full rounded-full transition-all duration-300"
                style={{ width: `${progressPercent}%` }}
              ></div>
            </div>
          </div>
        </div>
      )}

      {/* State 3: Analytics Console Active */}
      {readyPlatforms.length > 0 && (
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
              <span className="text-xl font-black text-brand-navy mt-1 block truncate" title={`${startDate} to ${endDate}`}>
                {startDate.split('-').slice(1).join('/')} - {endDate.split('-').slice(1).join('/')}
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
              <p className="text-xs text-brand-navy/70">Please refresh or reset the ingestion pipeline.</p>
              <button
                onClick={refetchInsights}
                className="px-4 py-2 rounded-xl bg-brand-navy text-white text-xs font-bold"
              >
                Retry Request
              </button>
            </div>
          ) : isInsightsLoading ? (
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
                    datasets={datasets}
                    dateBounds={dateBounds}
                  />
                </div>
                <div>
                  <DeepDive selectedDate={selectedDate} dayData={selectedDayData} />
                </div>
              </div>

              {/* Heatmap Section */}
              <BehavioralHeatmap 
                data={hourlyHeatmapData} 
                activePlatforms={platformsToQuery} 
                totalScopeHours={totalScopeHours}
                dayCount={dayCount}
              />
            </div>
          )}
        </div>
      )}
    </div>
  );
}

export default function DashboardContainer() {
  return (
    <QueryClientProvider client={queryClient}>
      <DashboardContent />
    </QueryClientProvider>
  );
}
