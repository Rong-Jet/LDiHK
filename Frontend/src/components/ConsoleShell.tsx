import React, { useState } from 'react';
import {
  RefreshCw, Database, ShieldAlert, UploadCloud, Key, Copy, Check, LogOut,
  Eye, EyeOff, ShieldCheck, Lock, AlertTriangle, CloudOff, Info, X, Trash2,
} from 'lucide-react';
import UploadZone from './UploadZone';
import { UploadProvider, useUploadController } from '../hooks/useUploadController';
import type { BackendStatus } from '../hooks/useBackendStatus';
import type { ConsoleSession } from '../hooks/useConsoleSession';
import { deleteMyData, describeApiError, isPendingEnrichment, usesLocalMockApi, type ImportStatus } from '../lib/api';
import { daysInclusive, formatCalendarValue, utcMsToYmd } from '../lib/dates';
import { platformList } from '../lib/profile';

/** One-time message shown on the login screen after the account was deleted. */
const DELETION_NOTICE_KEY = 'ldihk_deletion_notice';

export type ConsoleTab = 'dashboard' | 'population' | 'risk';

const TABS: { id: ConsoleTab; href: string; label: string; domId: string }[] = [
  { id: 'dashboard', href: '/dashboard', label: 'Personal Insights', domId: 'tab-personal-insights' },
  { id: 'population', href: '/population', label: 'Population Benchmark', domId: 'tab-population-benchmark' },
  { id: 'risk', href: '/risk', label: 'Mental Health Risk', domId: 'tab-mental-health-risk' },
];

/** Tells the user why the first request on the free tier is slow. */
export function ServerWakeBanner({ backend }: { backend: BackendStatus }) {
  if (backend.state === 'waking') {
    return (
      <div className="mb-6 bg-brand-teal/10 border border-brand-teal/25 rounded-2xl p-4 text-brand-navy text-xs leading-relaxed flex items-center gap-3 text-left" role="status">
        <RefreshCw className="w-5 h-5 text-brand-teal animate-spin shrink-0" />
        <div className="flex-grow">
          <span className="font-extrabold block">Waking the server — this can take up to a minute on the free tier.</span>
          <span className="text-brand-navy/60">Your dashboard loads automatically once the analytics server answers ({backend.elapsedSeconds}s).</span>
        </div>
      </div>
    );
  }
  if (backend.state === 'unreachable') {
    return (
      <div className="mb-6 bg-brand-peach/10 border border-brand-peach/30 rounded-2xl p-4 text-brand-navy text-xs leading-relaxed flex flex-col sm:flex-row sm:items-center gap-3 text-left" role="alert">
        <CloudOff className="w-5 h-5 text-brand-peach shrink-0" />
        <div className="flex-grow">
          <span className="font-extrabold block">The analytics server is unreachable right now.</span>
          <span className="text-brand-navy/60">
            {backend.message || 'It did not answer within two minutes. It may be restarting or temporarily down.'}
          </span>
        </div>
        <button
          onClick={backend.retry}
          className="px-4 py-2 rounded-xl bg-brand-navy text-white text-xs font-bold cursor-pointer shrink-0"
        >
          Retry
        </button>
      </div>
    );
  }
  return null;
}

export function MockModeBanner() {
  if (!usesLocalMockApi) return null;
  return (
    <div className="mb-6 bg-amber-50 border border-amber-200 rounded-2xl px-4 py-2.5 text-amber-900 text-[11px] font-semibold flex items-center gap-2 text-left">
      <Info className="w-4 h-4 text-amber-600 shrink-0" />
      Mock mode: all numbers on this page are simulated by local mock routes, not real uploaded data.
    </div>
  );
}

/** Data older than this (days since its newest day) gets the stale-data notice. */
const STALE_DATA_DAYS = 30;
const STALE_DISMISSED_KEY = 'ldihk_stale_notice_dismissed';

function readStaleDismissed(): string | null {
  try {
    return sessionStorage.getItem(STALE_DISMISSED_KEY);
  } catch {
    return null;
  }
}

interface PlatformEnd {
  platform: string;
  /** Newest day with data for this platform (YYYY-MM-DD). */
  date: string;
}

/** "Instagram", "Instagram and TikTok", "Instagram, TikTok and Spotify". */
function platformNames(platforms: string[]): string {
  const names = platforms.map((platform) => {
    const name = platformList([platform]);
    return name.charAt(0).toUpperCase() + name.slice(1);
  });
  return names.length > 1 ? `${names.slice(0, -1).join(', ')} and ${names.at(-1)}` : names.join('');
}

function ageDaysOf(date: string): number {
  return daysInclusive(date, utcMsToYmd(Date.now())) - 1;
}

function describeEnd(date: string): string {
  const ageDays = ageDaysOf(date);
  const age = ageDays >= 60 ? `${Math.round(ageDays / 30.4)} months` : `${ageDays} days`;
  return `${formatCalendarValue(date, { day: 'numeric', month: 'long', year: 'numeric' })} (${age} ago)`;
}

/**
 * The console scales every view to the newest data point, so an old export
 * looks current. Names each platform whose data ended more than
 * STALE_DATA_DAYS ago and offers a newer upload. On the health tab the notice
 * cannot be dismissed: the risk indicator then describes the past (or mixes
 * current and outdated platforms), not today.
 */
function StaleDataNotice({ ends, activeTab, onUpload }: {
  ends: PlatformEnd[];
  activeTab: ConsoleTab;
  onUpload: () => void;
}) {
  const [dismissedFor, setDismissedFor] = useState(readStaleDismissed);
  const stale = ends.filter((end) => ageDaysOf(end.date) > STALE_DATA_DAYS);
  const isHealth = activeTab === 'risk';
  const dismissKey = stale.map((end) => `${end.platform}:${end.date}`).join(',');
  if (stale.length === 0) return null;
  if (!isHealth && dismissedFor === dismissKey) return null;

  const dismiss = () => {
    try {
      sessionStorage.setItem(STALE_DISMISSED_KEY, dismissKey);
    } catch {
      // Private mode: dismissed until the page is reloaded.
    }
    setDismissedFor(dismissKey);
  };
  const allStale = stale.length === ends.length;
  const names = platformNames(stale.map((end) => end.platform));
  const title = stale.length === 1
    ? `${allStale && ends.length === 1 ? 'Your data' : `Your ${names} data`} ends on ${describeEnd(stale[0].date)}`
    : allStale
      ? `Your data ends on ${describeEnd([...ends].map((end) => end.date).sort().at(-1)!)}`
      : `Your ${names} data is out of date`;
  const explanation = allStale
    ? isHealth
      ? 'This health analysis describes your usage up to that date, not your current habits. '
      : 'All charts end there, so recent weeks are missing. '
    : isHealth
      ? `This health analysis combines all platforms, so it mixes your current usage with outdated ${names} data. `
      : `${names} ${stale.length === 1 ? 'stops' : 'stop'} there, so recent ${names} use is missing from the charts and totals. `;

  return (
    <div className="mb-6 bg-amber-50 border border-amber-200 rounded-2xl p-4 text-brand-navy text-xs leading-relaxed flex flex-col sm:flex-row sm:items-start gap-3 text-left" role="status">
      <AlertTriangle className="w-5 h-5 text-amber-600 shrink-0 mt-0.5" />
      <div className="flex-grow">
        <span className="font-extrabold uppercase tracking-wider text-[10px] block mb-0.5 text-amber-700">{title}</span>
        {stale.length > 1 && (
          <ul className="mb-1">
            {stale.map((end) => (
              <li key={end.platform}>
                <b>{platformNames([end.platform])}</b>: ends on {describeEnd(end.date)}
              </li>
            ))}
          </ul>
        )}
        {explanation}
        You can update your analysis at any time by uploading a newer {names} export of the same account; data you
        already uploaded is kept and duplicates are skipped.
      </div>
      <div className="flex items-center gap-2 shrink-0">
        <button
          onClick={onUpload}
          className="px-3 py-1.5 rounded-lg bg-brand-teal text-white text-[11px] font-bold cursor-pointer flex items-center gap-1.5"
        >
          <UploadCloud className="w-3.5 h-3.5" />
          Upload newer data
        </button>
        {!isHealth && (
          <button
            onClick={dismiss}
            className="p-1.5 rounded-lg border border-brand-navy/15 text-brand-navy/60 hover:text-brand-navy cursor-pointer"
            title="Dismiss"
          >
            <X className="w-3.5 h-3.5" />
          </button>
        )}
      </div>
    </div>
  );
}

function ConsoleTitle() {
  return (
    <div>
      <h1 className="text-3xl font-extrabold text-brand-navy tracking-tight">Analytics Console</h1>
      <p className="text-sm text-brand-navy/60 mt-1">Manage, process, and query your social media data pipelines.</p>
    </div>
  );
}

function readDeletionNotice(): string | null {
  try {
    const notice = sessionStorage.getItem(DELETION_NOTICE_KEY);
    if (notice) sessionStorage.removeItem(DELETION_NOTICE_KEY);
    return notice;
  } catch {
    return null;
  }
}

/** Confirms and performs the permanent deletion of the account. */
function DeleteDataDialog({ session, onClose }: { session: ConsoleSession; onClose: () => void }) {
  const [confirmInput, setConfirmInput] = useState('');
  const [pending, setPending] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const token = session.sessionToken ?? '';
  const matches = confirmInput.trim() === token;

  const handleDelete = async () => {
    if (!matches || pending) return;
    setPending(true);
    setError(null);
    try {
      const result = await deleteMyData(token, confirmInput.trim());
      try {
        sessionStorage.setItem(
          DELETION_NOTICE_KEY,
          `Your data has been deleted: ${result.events_deleted.toLocaleString()} events and ${result.imports_deleted} import(s). This LDiHK-ID no longer exists.`
        );
      } catch {
        // Session storage unavailable: the deletion still happened.
      }
      session.logout();
    } catch (deleteError) {
      setError(describeApiError(deleteError, 'Deleting your data failed. Nothing was changed; please retry.'));
      setPending(false);
    }
  };

  return (
    <div className="fixed inset-0 z-50 bg-brand-navy/40 backdrop-blur-sm flex items-center justify-center p-4" role="dialog" aria-modal="true" aria-labelledby="delete-data-title">
      <div className="bg-white rounded-3xl shadow-2xl max-w-md w-full p-6 text-left space-y-4 border border-brand-peach/30">
        <div className="flex items-start gap-3">
          <div className="w-10 h-10 rounded-xl bg-brand-peach/15 flex items-center justify-center text-brand-peach shrink-0">
            <Trash2 className="w-5 h-5" />
          </div>
          <div>
            <h3 id="delete-data-title" className="font-black text-brand-navy text-lg">Delete all my data</h3>
            <p className="text-xs text-brand-navy/70 leading-relaxed mt-1">
              This permanently deletes your usage history, imports and LDiHK-ID from our database and removes uploaded archives from storage. It cannot be undone.
            </p>
          </div>
        </div>
        <label className="block space-y-1.5">
          <span className="text-[10px] uppercase tracking-wider font-extrabold text-brand-navy/50 block">Type your LDiHK-ID to confirm</span>
          <input
            type="text"
            value={confirmInput}
            onChange={(event) => setConfirmInput(event.target.value)}
            autoComplete="off"
            spellCheck={false}
            disabled={pending}
            className="w-full bg-white border border-brand-navy/20 rounded-2xl px-4 py-3 text-sm font-mono text-brand-navy focus:outline-none focus:ring-2 focus:ring-brand-peach/30 focus:border-brand-peach disabled:opacity-60"
          />
        </label>
        {error && <p className="text-xs font-semibold text-brand-peach" role="alert">{error}</p>}
        <div className="flex justify-end gap-3 pt-1">
          <button onClick={onClose} disabled={pending} className="px-4 py-2.5 rounded-xl border border-brand-navy/15 text-brand-navy text-xs font-bold cursor-pointer disabled:opacity-60">
            Cancel
          </button>
          <button
            onClick={handleDelete}
            disabled={!matches || pending}
            className="px-4 py-2.5 rounded-xl bg-brand-peach text-white text-xs font-bold flex items-center gap-2 cursor-pointer disabled:opacity-50 disabled:cursor-not-allowed"
          >
            {pending ? <RefreshCw className="w-3.5 h-3.5 animate-spin" /> : <Trash2 className="w-3.5 h-3.5" />}
            Delete permanently
          </button>
        </div>
      </div>
    </div>
  );
}

function LoginScreen({ backend, session }: { backend: BackendStatus; session: ConsoleSession }) {
  const [loginIdInput, setLoginIdInput] = useState('');
  const [showLoginPassword, setShowLoginPassword] = useState(false);
  const [deletionNotice] = useState(readDeletionNotice);
  const { pending, error } = session.loginState;

  const handleLoginSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    if (!pending && loginIdInput.trim()) {
      void session.login(loginIdInput);
    }
  };

  return (
    <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 py-10 text-left">
      {/* Subheader */}
      <div className="mb-10 pb-6 border-b border-brand-navy/10">
        <ConsoleTitle />
      </div>

      <MockModeBanner />
      <ServerWakeBanner backend={backend} />

      {deletionNotice && (
        <div className="mb-6 bg-brand-teal/10 border border-brand-teal/25 rounded-2xl p-4 text-brand-navy text-xs font-semibold flex items-center gap-3" role="status">
          <ShieldCheck className="w-5 h-5 text-brand-teal shrink-0" />
          {deletionNotice}
        </div>
      )}

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
                  Enter your unique LDiHK-ID to retrieve your saved analytics dashboard.
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
                    placeholder="e.g. ldihk-cosmic-pegasus-k3j9x2m4q7ab"
                    autoComplete="current-password"
                    required
                    disabled={pending}
                    className="w-full bg-white border border-brand-navy/20 rounded-2xl pl-4 pr-12 py-3.5 text-sm font-bold text-brand-navy placeholder-brand-navy/30 focus:outline-none focus:ring-2 focus:ring-brand-teal/30 focus:border-brand-teal transition-all disabled:opacity-60"
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

              {error && (
                <div className="flex gap-2 p-3 rounded-2xl bg-brand-peach/10 border border-brand-peach/30 text-xs text-brand-navy leading-relaxed" role="alert">
                  <AlertTriangle className="w-4 h-4 text-brand-peach shrink-0 mt-0.5" />
                  <span>{error}</span>
                </div>
              )}

              <button
                type="submit"
                disabled={pending}
                className="w-full px-5 py-4 rounded-2xl bg-brand-navy hover:bg-brand-navy/95 text-white font-bold text-sm transition-all shadow-md shadow-brand-navy/10 hover:shadow-lg duration-150 flex items-center justify-center gap-2 cursor-pointer disabled:cursor-wait disabled:opacity-80"
              >
                {pending ? <RefreshCw className="w-4 h-4 text-brand-peach animate-spin" /> : <Key className="w-4 h-4 text-brand-peach" />}
                {pending ? 'Checking your ID…' : 'Access Dashboard'}
              </button>
              {pending && !backend.isReady && (
                <p className="text-[10px] text-brand-navy/50 text-center">The server is waking up; this can take up to a minute.</p>
              )}
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
              <UploadZone sessionToken={null} onSessionGenerated={session.adoptGeneratedSession} />
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

function StatusPill({ status }: { status: ConsoleSession['pipelineStatus'] }) {
  return (
    <div className="px-4 py-2.5 rounded-xl bg-brand-beige text-xs font-bold text-brand-navy border border-brand-navy/10 flex items-center gap-2 shadow-sm">
      <span
        className={`w-2.5 h-2.5 rounded-full ${
          status === 'READY'
            ? 'bg-brand-teal animate-pulse'
            : status === 'PROCESSING'
            ? 'bg-brand-peach animate-spin'
            : 'bg-brand-navy/40'
        }`}
      ></span>
      Pipeline Status:{' '}
      <span className={`uppercase font-extrabold ${status === 'READY' ? 'text-brand-teal' : status === 'PROCESSING' ? 'text-brand-peach' : 'text-brand-navy/40'}`}>
        {status === 'PROCESSING'
          ? 'Processing Data...'
          : status === 'READY'
          ? 'Active'
          : 'Awaiting Upload'}
      </span>
    </div>
  );
}

function processingTitle(importStatus: ImportStatus | null) {
  if (importStatus?.status === 'queued') return 'Worker Queueing Import...';
  if (isPendingEnrichment(importStatus)) return 'Enriching Video Durations...';
  if (importStatus?.status === 'running') return 'Extracting and Normalizing Takeout...';
  return 'Checking Import Status...';
}

function ProcessingPanel({ session, description }: { session: ConsoleSession; description: string }) {
  const importStatus = session.importStatus;
  const recordsSeen = importStatus?.records_seen || 0;
  const recordsImported = importStatus?.records_imported || 0;
  const progressPercent = !importStatus
    ? 5
    : importStatus.status === 'queued'
      ? 10
      : recordsSeen > 0
        ? Math.min(95, (recordsImported / recordsSeen) * 100)
        : 20;

  return (
    <div className="bg-brand-beige border border-brand-navy/15 rounded-3xl p-12 text-center max-w-2xl mx-auto shadow-sm space-y-6">
      <div className="w-16 h-16 rounded-full bg-white flex items-center justify-center mx-auto shadow-sm text-brand-teal border border-brand-navy/10">
        <RefreshCw className="w-8 h-8 animate-spin" />
      </div>
      <div>
        <h2 className="text-xl font-bold text-brand-navy">{processingTitle(importStatus)}</h2>
        <p className="text-xs text-brand-navy/60 mt-2 max-w-md mx-auto leading-relaxed">{description}</p>
      </div>

      <div className="grid grid-cols-3 gap-4 bg-white/50 p-4 rounded-2xl border border-brand-navy/5 max-w-md mx-auto text-left">
        <div>
          <span className="text-[9px] uppercase tracking-wider font-extrabold text-brand-navy/50 block">Status</span>
          <span className="text-xs font-black text-brand-teal capitalize">{importStatus?.status || 'queued'}</span>
        </div>
        <div>
          <span className="text-[9px] uppercase tracking-wider font-extrabold text-brand-navy/50 block">Records Ingested</span>
          <span className="text-xs font-black text-brand-navy">{recordsImported} / {recordsSeen}</span>
        </div>
        <div>
          <span className="text-[9px] uppercase tracking-wider font-extrabold text-brand-navy/50 block">Warnings</span>
          <span className="text-xs font-black text-brand-peach">{importStatus?.warnings_count || 0}</span>
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
        {session.importPollError && (
          <p className="text-[10px] text-brand-peach font-semibold pt-1">
            Having trouble reaching the server ({describeApiError(session.importPollError)}). Still retrying…
          </p>
        )}
      </div>
    </div>
  );
}

/** Import failure / timeout notices plus the small background-progress notes. */
function ImportNotices({ session }: { session: ConsoleSession }) {
  const { notice } = session;
  const hasData = session.readyPlatforms.length > 0;

  return (
    <>
      {notice && (
        <div className="mb-6 bg-brand-peach/10 border border-brand-peach/30 rounded-2xl p-4 text-brand-navy text-xs leading-relaxed flex flex-col sm:flex-row sm:items-start gap-3 text-left" role="alert">
          <AlertTriangle className="w-5 h-5 text-brand-peach shrink-0 mt-0.5" />
          <div className="flex-grow">
            <span className="font-extrabold uppercase tracking-wider text-[10px] block mb-0.5 text-brand-peach">
              {notice.kind === 'failed' ? 'Import failed' : notice.kind === 'timeout' ? 'Import still processing' : 'Import status unavailable'}
            </span>
            <span className="break-words">{notice.message}</span>
            {notice.kind === 'failed' && (
              <span className="block text-brand-navy/60 mt-1">
                {notice.guide
                  ? '"How do I get my export?" in the upload panel shows which options to select.'
                  : 'Make sure the ZIP is an unmodified platform export (e.g. Google Takeout with YouTube history), then upload it again.'}
              </span>
            )}
          </div>
          <div className="flex items-center gap-2 shrink-0">
            {notice.kind === 'timeout' && session.canResumeImport && (
              <button
                onClick={session.resumeImportPolling}
                className="px-3 py-1.5 rounded-lg bg-brand-navy text-white text-[11px] font-bold cursor-pointer"
              >
                Check again
              </button>
            )}
            <button
              onClick={session.dismissNotice}
              className="p-1.5 rounded-lg border border-brand-navy/15 text-brand-navy/60 hover:text-brand-navy cursor-pointer"
              title="Dismiss"
            >
              <X className="w-3.5 h-3.5" />
            </button>
          </div>
        </div>
      )}

      {hasData && session.pipelineStatus === 'PROCESSING' && (
        <div className="mb-6 bg-brand-beige/60 border border-brand-navy/10 rounded-2xl px-4 py-3 text-brand-navy text-xs flex items-center gap-3 text-left" role="status">
          <RefreshCw className="w-4 h-4 text-brand-peach animate-spin shrink-0" />
          <span>
            <span className="font-bold">{processingTitle(session.importStatus)}</span>{' '}
            <span className="text-brand-navy/60">
              Your new upload is being processed ({session.importStatus?.records_imported || 0} records so far). The charts update automatically when it finishes.
            </span>
          </span>
        </div>
      )}

      {hasData && session.isEnriching && (
        <div className="mb-6 bg-brand-teal/5 border border-brand-teal/20 rounded-2xl px-4 py-2.5 text-brand-navy text-[11px] flex items-center gap-2 text-left" role="status">
          <RefreshCw className="w-3.5 h-3.5 text-brand-teal animate-spin shrink-0" />
          Enriching video durations… watch-time figures may still shift slightly and refresh automatically.
        </div>
      )}
    </>
  );
}

interface ConsoleShellProps {
  activeTab: ConsoleTab;
  backend: BackendStatus;
  session: ConsoleSession;
  /** Page-specific view reset (dates, filters) for the "Reset Console" button. */
  onResetView?: () => void;
  awaitingDescription: string;
  processingDescription: string;
  /** Rendered once the workspace has at least one platform with data. */
  children: React.ReactNode;
}

export default function ConsoleShell(props: ConsoleShellProps) {
  return (
    <UploadProvider onUploadComplete={props.session.registerImport}>
      <ConsoleShellBody {...props} />
    </UploadProvider>
  );
}

function ConsoleShellBody({
  activeTab,
  backend,
  session,
  onResetView,
  awaitingDescription,
  processingDescription,
  children,
}: ConsoleShellProps) {
  const [showUploadZone, setShowUploadZone] = useState(false);
  const [copiedToken, setCopiedToken] = useState(false);
  const [showToken, setShowToken] = useState(false);
  const [isResetting, setIsResetting] = useState(false);
  const [showDeleteDialog, setShowDeleteDialog] = useState(false);
  const upload = useUploadController();

  const { sessionToken, pipelineStatus, readyPlatforms, phase } = session;

  if (!sessionToken) {
    return <LoginScreen backend={backend} session={session} />;
  }

  const copyToClipboard = () => {
    navigator.clipboard.writeText(sessionToken);
    setCopiedToken(true);
    setTimeout(() => setCopiedToken(false), 2000);
  };

  const handleLogout = () => {
    setShowUploadZone(false);
    session.logout();
  };

  const toggleUploadZone = () => {
    // Upload state is shared by every upload zone, so a finished upload would
    // still show "Upload Complete" when the panel is opened later.
    if (!showUploadZone && upload.phase === 'SUCCESS') upload.reset();
    setShowUploadZone(!showUploadZone);
  };

  const handleReset = async () => {
    setIsResetting(true);
    try {
      onResetView?.();
      await session.resetConsole();
    } finally {
      setIsResetting(false);
    }
  };

  const hasData = phase === 'ready' && readyPlatforms.length > 0;

  return (
    <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 py-10">
      {/* Header and Controller Row */}
      <div className="mb-6 flex flex-col md:flex-row md:items-center md:justify-between gap-6 pb-6 border-b border-brand-navy/10 text-left">
        <ConsoleTitle />

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
          {phase === 'ready' && <StatusPill status={pipelineStatus} />}

          {/* Ingest Data Toggle Button */}
          {hasData && (
            <button
              onClick={toggleUploadZone}
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
          {hasData && (
            <button
              onClick={handleReset}
              disabled={isResetting}
              title={usesLocalMockApi
                ? 'Reset the simulated mock pipeline and all filters'
                : 'Clear results cached in this browser and reset filters, then reload from the server. Your uploaded data is not deleted.'}
              className="px-4 py-2.5 rounded-xl border border-brand-peach/30 hover:border-brand-peach/60 bg-brand-peach/10 text-brand-navy text-xs font-bold transition-all hover:shadow-md flex items-center gap-2 duration-150 cursor-pointer disabled:opacity-60"
            >
              <RefreshCw className={`w-3.5 h-3.5 text-brand-peach ${isResetting ? 'animate-spin' : ''}`} />
              Reset Console
            </button>
          )}

          {/* Delete My Data button */}
          <button
            onClick={() => setShowDeleteDialog(true)}
            className="px-4 py-2.5 rounded-xl border border-brand-peach/30 hover:bg-brand-peach/10 text-brand-navy text-xs font-bold transition-all flex items-center gap-2 duration-150 cursor-pointer"
            title="Permanently delete all data stored for this LDiHK-ID"
          >
            <Trash2 className="w-3.5 h-3.5 text-brand-peach" />
            Delete My Data
          </button>

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

      {showDeleteDialog && <DeleteDataDialog session={session} onClose={() => setShowDeleteDialog(false)} />}

      {/* View Switcher Sub-Navigation Tabs */}
      {/* Scrolls sideways on narrow phones instead of widening the page. */}
      <div className="mb-8 border-b border-brand-navy/10 flex gap-4 text-left overflow-x-auto whitespace-nowrap">
        {TABS.map((tab) => (
          <a
            key={tab.id}
            href={tab.href}
            className={tab.id === activeTab
              ? 'shrink-0 px-4 py-3 text-sm font-extrabold border-b-2 border-brand-teal text-brand-teal transition-all'
              : 'shrink-0 px-4 py-3 text-sm font-bold border-b-2 border-transparent text-brand-navy/50 hover:text-brand-navy transition-all'}
            id={tab.domId}
          >
            {tab.label}
          </a>
        ))}
      </div>

      <MockModeBanner />
      <ServerWakeBanner backend={backend} />
      {phase === 'ready' && <ImportNotices session={session} />}
      {hasData && pipelineStatus !== 'PROCESSING' && !showUploadZone && (
        <StaleDataNotice
          ends={readyPlatforms.flatMap((platform) => {
            const date = session.datasets[platform]?.max_date;
            return date ? [{ platform, date }] : [];
          })}
          activeTab={activeTab}
          onUpload={() => {
            if (upload.phase === 'SUCCESS') upload.reset();
            setShowUploadZone(true);
          }}
        />
      )}

      {/* Collapsible Upload Zone Drawer */}
      {showUploadZone && hasData && (
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
          <UploadZone sessionToken={sessionToken} guideFocus={session.notice?.guide ?? null} />
        </div>
      )}

      {/* Workspace loading */}
      {phase === 'loading' && (
        <div className="h-[320px] flex flex-col items-center justify-center gap-3 bg-white border border-brand-navy/10 rounded-3xl text-center">
          <RefreshCw className="w-8 h-8 animate-spin text-brand-teal" />
          <p className="text-xs font-semibold text-brand-navy/60">
            {backend.isReady ? 'Loading your workspace…' : 'Waiting for the analytics server…'}
          </p>
        </div>
      )}

      {/* Workspace failed to load */}
      {phase === 'error' && (
        <div className="bg-brand-peach/10 border border-brand-peach/30 rounded-3xl p-8 text-center text-brand-navy flex flex-col items-center gap-3">
          <ShieldAlert className="w-10 h-10 text-brand-peach" />
          <h4 className="font-bold">Could not load your workspace</h4>
          <p className="text-xs text-brand-navy/70 max-w-md">{describeApiError(session.meError)}</p>
          <div className="flex items-center gap-3">
            <button
              onClick={() => session.refetchMe()}
              disabled={session.isRefreshingMe}
              className="px-4 py-2 rounded-xl bg-brand-navy text-white text-xs font-bold cursor-pointer disabled:opacity-60"
            >
              {session.isRefreshingMe ? 'Retrying…' : 'Retry Request'}
            </button>
            <button
              onClick={handleLogout}
              className="px-4 py-2 rounded-xl border border-brand-navy/15 text-brand-navy text-xs font-bold cursor-pointer"
            >
              Log Out
            </button>
          </div>
        </div>
      )}

      {/* State 1: Upload Needed (Only if no datasets are ready) */}
      {phase === 'ready' && readyPlatforms.length === 0 && pipelineStatus !== 'PROCESSING' && (
        <div className="space-y-12">
          <UploadZone sessionToken={sessionToken} guideFocus={session.notice?.guide ?? null} />

          {/* Visual Scaffolding Placeholders */}
          <div className="border border-brand-navy/10 rounded-3xl p-8 bg-brand-beige/20 text-center max-w-xl mx-auto space-y-3">
            <Database className="w-8 h-8 text-brand-navy/30 mx-auto" />
            <h3 className="font-bold text-brand-navy text-sm">Awaiting Ingress Stream</h3>
            <p className="text-xs text-brand-navy/60 leading-relaxed">{awaitingDescription}</p>
          </div>
        </div>
      )}

      {/* State 2: Upload completed, but server is processing (Only if no datasets are ready) */}
      {phase === 'ready' && readyPlatforms.length === 0 && pipelineStatus === 'PROCESSING' && (
        <ProcessingPanel session={session} description={processingDescription} />
      )}

      {/* State 3: Workspace has data */}
      {hasData && children}
    </div>
  );
}
