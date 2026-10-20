import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { useQuery, useQueryClient } from '@tanstack/react-query';
import {
  ApiError,
  apiRoutes,
  createImport,
  describeApiError,
  fetchImportStatus,
  fetchMe,
  updateProfile,
  type UserProfile,
  isApiStatus,
  isImportInFlight,
  isPendingEnrichment,
  usesLocalMockApi,
  type DatasetSummary,
  type ImportStatus,
  type MeResponse,
} from '../lib/api';
import { getBrowserTimeZone, isYmd, maxYmd, minYmd, type DateBounds } from '../lib/dates';
import { isValidLdihkId } from '../lib/ldihkId';
import { EMPTY_PROFILE } from '../lib/profile';
import { describeImportFailure } from '../lib/importErrors';
import type { GuidePlatform } from '../components/ExportGuide';

const TOKEN_KEY = 'ldihk_session_token';
const IMPORT_ID_KEY = 'ldihk_current_import_id';
const IMPORT_META_KEY = 'ldihk_current_import_meta';

export const IMPORT_POLL_INTERVAL_MS = 3_000;
export const ENRICHMENT_POLL_INTERVAL_MS = 5_000;
export const IMPORT_MAX_WAIT_MS = 30 * 60 * 1000;

/** Platforms the live backend can ingest and query today. */
export const LIVE_PLATFORMS = ['youtube', 'instagram', 'tiktok'];
/** The local mock routes additionally simulate Spotify. */
export const MOCK_PLATFORMS = ['youtube', 'instagram', 'tiktok', 'spotify'];
export const QUERYABLE_PLATFORMS = usesLocalMockApi ? MOCK_PLATFORMS : LIVE_PLATFORMS;

export type SessionPhase = 'signed_out' | 'loading' | 'error' | 'ready';
export type PipelineStatus = 'PROCESSING' | 'READY' | 'NOT_UPLOADED';

export interface ImportNotice {
  kind: 'failed' | 'timeout' | 'lost';
  importId: string;
  message: string;
  /** Export guide tab that explains how to fix a failed import. */
  guide?: GuidePlatform | null;
}

interface TrackedImport {
  id: string;
  owner: string;
  startedAt: number;
}

function getStorage(): Storage | null {
  try {
    return typeof window !== 'undefined' ? window.localStorage : null;
  } catch {
    return null;
  }
}

function readStoredToken(): string | null {
  return getStorage()?.getItem(TOKEN_KEY) || null;
}

function writeTrackedImport(tracked: TrackedImport | null) {
  const store = getStorage();
  if (!store) return;
  if (tracked) {
    store.setItem(IMPORT_ID_KEY, tracked.id);
    store.setItem(IMPORT_META_KEY, JSON.stringify({ owner: tracked.owner, startedAt: tracked.startedAt }));
  } else {
    store.removeItem(IMPORT_ID_KEY);
    store.removeItem(IMPORT_META_KEY);
  }
}

function readTrackedImport(owner: string | null): TrackedImport | null {
  const store = getStorage();
  if (!store || !owner) return null;
  const id = store.getItem(IMPORT_ID_KEY);
  if (!id) return null;

  let meta: { owner?: unknown; startedAt?: unknown } | null = null;
  try {
    meta = JSON.parse(store.getItem(IMPORT_META_KEY) || 'null');
  } catch {
    meta = null;
  }
  // An import tracked for a different LDiHK-ID is stale: drop it.
  if (meta && typeof meta.owner === 'string' && meta.owner !== owner) {
    writeTrackedImport(null);
    return null;
  }
  return {
    id,
    owner,
    startedAt: typeof meta?.startedAt === 'number' ? meta.startedAt : Date.now(),
  };
}

function parseTimestamp(value: string | null | undefined): number | null {
  if (!value) return null;
  const ms = Date.parse(value);
  return Number.isFinite(ms) ? ms : null;
}

function hasQueryableData(summary: DatasetSummary | undefined): summary is DatasetSummary & { min_date: string; max_date: string } {
  return !!summary && (summary.event_count ?? 0) > 0 && isYmd(summary.min_date) && isYmd(summary.max_date);
}

export interface ConsoleSessionOptions {
  backendReady: boolean;
  /** IANA timezone for /api/me date bounds. Defaults to the browser timezone. */
  timeZone?: string;
}

export function useConsoleSession({ backendReady, timeZone: requestedTimeZone }: ConsoleSessionOptions) {
  const queryClient = useQueryClient();
  const timeZone = useMemo(() => requestedTimeZone || getBrowserTimeZone(), [requestedTimeZone]);

  const [sessionToken, setSessionToken] = useState<string | null>(() => readStoredToken());
  const [tracked, setTracked] = useState<TrackedImport | null>(() => readTrackedImport(readStoredToken()));
  const [pollingStopped, setPollingStopped] = useState(false);
  const [importNotice, setImportNotice] = useState<ImportNotice | null>(null);
  const [dismissedImportIds, setDismissedImportIds] = useState<string[]>([]);
  const [loginState, setLoginState] = useState<{ pending: boolean; error: string | null }>({ pending: false, error: null });

  // Imports we have finished handling in this page view; never re-adopt them from /api/me.
  const handledImportIds = useRef(new Set<string>());
  const completedHandledFor = useRef<string | null>(null);

  // -------------------------------------------------------------------------
  // GET /api/me: login validation, per-platform date bounds, latest import.
  // `null` means the ID has never uploaded anything (404 unknown_ldihk_id).
  // -------------------------------------------------------------------------
  const meQuery = useQuery<MeResponse | null>({
    queryKey: ['me', sessionToken, timeZone],
    queryFn: async ({ signal }) => {
      try {
        return await fetchMe(sessionToken as string, timeZone, signal);
      } catch (error) {
        if (isApiStatus(error, 404)) return null;
        throw error;
      }
    },
    enabled: !!sessionToken && backendReady,
    staleTime: 30_000,
  });
  const me = meQuery.data ?? null;

  // -------------------------------------------------------------------------
  // Import status polling. Keeps polling through transient errors, stops on
  // 403/404, on failure, on completion (+ enrichment) or after ~30 minutes.
  // -------------------------------------------------------------------------
  const importQuery = useQuery<ImportStatus>({
    queryKey: ['importStatus', tracked?.id ?? null, sessionToken],
    queryFn: ({ signal }) => fetchImportStatus(sessionToken as string, (tracked as TrackedImport).id, signal),
    enabled: !!tracked && !!sessionToken && backendReady && !pollingStopped,
    retry: false,
    refetchInterval: (query) => {
      if (isApiStatus(query.state.error, 403, 404)) return false;
      const data = query.state.data;
      if (!data) return IMPORT_POLL_INTERVAL_MS;
      if (data.status === 'failed') return false;
      if (data.status === 'completed') return isPendingEnrichment(data) ? ENRICHMENT_POLL_INTERVAL_MS : false;
      return IMPORT_POLL_INTERVAL_MS;
    },
    refetchIntervalInBackground: true,
  });
  const importStatus = tracked ? importQuery.data ?? null : null;

  const invalidateDataQueries = useCallback(() => {
    queryClient.invalidateQueries({ predicate: (query) => query.queryKey[0] !== 'importStatus' });
  }, [queryClient]);

  const clearTracking = useCallback(() => {
    writeTrackedImport(null);
    setTracked(null);
    setPollingStopped(false);
  }, []);

  const finishTracking = useCallback((importId: string, notice: ImportNotice | null) => {
    handledImportIds.current.add(importId);
    clearTracking();
    if (notice) setImportNotice(notice);
  }, [clearTracking]);

  const startTracking = useCallback((next: TrackedImport) => {
    writeTrackedImport(next);
    setTracked(next);
    setPollingStopped(false);
    setImportNotice(null);
  }, []);

  // React to status transitions of the tracked import.
  useEffect(() => {
    if (!tracked) return;
    if (isApiStatus(importQuery.error, 403, 404)) {
      finishTracking(tracked.id, {
        kind: 'lost',
        importId: tracked.id,
        message: isApiStatus(importQuery.error, 403)
          ? 'The last upload belongs to a different LDiHK-ID, so its status cannot be shown here.'
          : 'The status of your last upload could not be found. If your data does not appear, please upload the archive again.',
      });
      invalidateDataQueries();
      return;
    }

    const data = importQuery.data;
    if (!data || data.import_id !== tracked.id) return;

    if (data.status === 'failed') {
      finishTracking(tracked.id, {
        kind: 'failed',
        importId: tracked.id,
        ...describeImportFailure(data.error_message),
      });
      invalidateDataQueries();
      return;
    }

    if (data.status === 'completed') {
      if (!isPendingEnrichment(data)) {
        finishTracking(tracked.id, null);
        invalidateDataQueries();
        return;
      }
      // Show data as soon as the import is completed; enrichment continues in the background.
      if (completedHandledFor.current !== tracked.id) {
        completedHandledFor.current = tracked.id;
        invalidateDataQueries();
      }
    }
  }, [tracked, importQuery.data, importQuery.error, finishTracking, invalidateDataQueries]);

  // Cap the total wait at ~30 minutes.
  useEffect(() => {
    if (!tracked || pollingStopped) return;
    const check = () => {
      if (Date.now() - tracked.startedAt <= IMPORT_MAX_WAIT_MS) return;
      if (importQuery.data?.status === 'completed') {
        // Only enrichment is slow; data is already visible. Stop quietly.
        finishTracking(tracked.id, null);
        return;
      }
      setPollingStopped(true);
      setImportNotice({
        kind: 'timeout',
        importId: tracked.id,
        message: 'Processing is taking longer than 30 minutes. It may still finish on the server; check again later.',
      });
    };
    check();
    const timer = setInterval(check, 15_000);
    return () => clearInterval(timer);
  }, [tracked, pollingStopped, importQuery.data?.status, finishTracking]);

  // Pick up an import that is still running on the server (e.g. started on another device).
  useEffect(() => {
    const latest = me?.latest_import;
    if (!sessionToken || tracked || !latest || handledImportIds.current.has(latest.import_id)) return;
    if (isImportInFlight(latest) || isPendingEnrichment(latest)) {
      startTracking({
        id: latest.import_id,
        owner: sessionToken,
        startedAt: parseTimestamp(latest.created_at) ?? Date.now(),
      });
    }
  }, [me, sessionToken, tracked, startTracking]);

  // -------------------------------------------------------------------------
  // Derived dataset state
  // -------------------------------------------------------------------------
  const datasets = useMemo<Record<string, DatasetSummary>>(() => me?.datasets ?? {}, [me]);

  const readyPlatforms = useMemo(
    () => QUERYABLE_PLATFORMS.filter((platform) => hasQueryableData(datasets[platform])),
    [datasets]
  );

  const boundsFor = useCallback((platforms: string[]): DateBounds | null => {
    let bounds: DateBounds | null = null;
    for (const platform of platforms) {
      const summary = datasets[platform];
      if (!hasQueryableData(summary)) continue;
      bounds = bounds
        ? { minDate: minYmd(bounds.minDate, summary.min_date), maxDate: maxYmd(bounds.maxDate, summary.max_date) }
        : { minDate: summary.min_date, maxDate: summary.max_date };
    }
    return bounds;
  }, [datasets]);

  const dateBounds = useMemo(() => boundsFor(readyPlatforms), [boundsFor, readyPlatforms]);

  const importInFlight = !!tracked && !pollingStopped
    && !(importStatus && (importStatus.status === 'completed' || importStatus.status === 'failed'));
  const isEnriching = !!tracked && isPendingEnrichment(importStatus);
  const pipelineStatus: PipelineStatus = importInFlight
    ? 'PROCESSING'
    : readyPlatforms.length > 0 ? 'READY' : 'NOT_UPLOADED';

  const phase: SessionPhase = !sessionToken
    ? 'signed_out'
    : meQuery.data !== undefined
      ? 'ready'
      : meQuery.isError ? 'error' : 'loading';

  // A failed latest import explains an empty workspace even after a reload.
  const latestImport = me?.latest_import ?? null;
  const derivedFailureNotice: ImportNotice | null = !importNotice
    && readyPlatforms.length === 0
    && !tracked
    && latestImport?.status === 'failed'
    && !dismissedImportIds.includes(latestImport.import_id)
    ? {
        kind: 'failed',
        importId: latestImport.import_id,
        ...describeImportFailure(latestImport.error_message),
      }
    : null;
  const notice = importNotice ?? derivedFailureNotice;

  // -------------------------------------------------------------------------
  // Actions
  // -------------------------------------------------------------------------
  const activateSession = useCallback((id: string) => {
    const store = getStorage();
    const previous = readStoredToken();
    store?.setItem(TOKEN_KEY, id);
    if (previous !== id) {
      // A different ID must never inherit the previous ID's import or cached data.
      writeTrackedImport(null);
      setTracked(null);
      setPollingStopped(false);
      setImportNotice(null);
      setDismissedImportIds([]);
      handledImportIds.current.clear();
      completedHandledFor.current = null;
      queryClient.clear();
    }
    setSessionToken(id);
  }, [queryClient]);

  const login = useCallback(async (rawId: string): Promise<boolean> => {
    const id = rawId.trim();
    if (!isValidLdihkId(id)) {
      setLoginState({
        pending: false,
        error: 'That does not look like an LDiHK-ID. IDs are 3-128 characters: letters, digits, dots, dashes or underscores.',
      });
      return false;
    }
    setLoginState({ pending: true, error: null });
    try {
      const profile = await fetchMe(id, timeZone);
      activateSession(id);
      queryClient.setQueryData(['me', id, timeZone], profile);
      setLoginState({ pending: false, error: null });
      return true;
    } catch (error) {
      let message: string;
      if (isApiStatus(error, 404)) {
        message = 'No dashboard found for this ID. Check it for typos, or upload an archive to create a new workspace.';
      } else if (error instanceof ApiError && (error.kind !== 'http' || error.status >= 500)) {
        message = error.status === 503
          ? 'The server is temporarily unavailable (database waking up). Please try again in a moment.'
          : 'The server is waking up or temporarily unreachable (free tier, up to a minute). Please try again shortly.';
      } else {
        message = describeApiError(error);
      }
      setLoginState({ pending: false, error: message });
      return false;
    }
  }, [activateSession, queryClient, timeZone]);

  /** New ID generated by the upload flow; it cannot exist on the backend yet. */
  const adoptGeneratedSession = useCallback((id: string) => {
    activateSession(id);
    setLoginState({ pending: false, error: null });
  }, [activateSession]);

  const logout = useCallback(() => {
    const store = getStorage();
    store?.removeItem(TOKEN_KEY);
    writeTrackedImport(null);
    setTracked(null);
    setPollingStopped(false);
    setImportNotice(null);
    setDismissedImportIds([]);
    handledImportIds.current.clear();
    completedHandledFor.current = null;
    setLoginState({ pending: false, error: null });
    setSessionToken(null);
    queryClient.clear();
  }, [queryClient]);

  /** Registers an uploaded object with the backend and starts polling it. */
  const registerImport = useCallback(async (s3Key: string, s3Bucket: string, token: string, profile?: UserProfile) => {
    const answered = profile && (profile.age_range || profile.sex);
    const result = await createImport(token, {
      s3_bucket: s3Bucket,
      s3_key: s3Key,
      ...(answered ? { age_range: profile.age_range, sex: profile.sex } : {}),
    });
    if (!result?.import_id) throw new Error('The server did not return an import ID.');
    startTracking({ id: result.import_id, owner: token, startedAt: Date.now() });
  }, [startTracking]);

  const dismissNotice = useCallback(() => {
    if (notice) {
      handledImportIds.current.add(notice.importId);
      setDismissedImportIds((ids) => (ids.includes(notice.importId) ? ids : [...ids, notice.importId]));
      // A timed-out import stays tracked so it can be resumed; dismissing gives up on it.
      if (notice.kind === 'timeout' && tracked?.id === notice.importId) clearTracking();
    }
    setImportNotice(null);
  }, [notice, tracked, clearTracking]);

  /** After a timeout: poll the same import again for another 30 minutes. */
  const resumeImportPolling = useCallback(() => {
    if (!tracked) return;
    startTracking({ ...tracked, startedAt: Date.now() });
  }, [tracked, startTracking]);

  /**
   * "Reset Console": in mock mode resets the simulated pipeline; in live mode it
   * clears what this browser cached (tracked import, notices, query results) and
   * reloads everything from the server. Uploaded data is never deleted.
   */
  const resetConsole = useCallback(async () => {
    if (usesLocalMockApi) {
      try {
        await fetch(apiRoutes.uploadUrl()); // GET resets the mock pipeline state
      } catch (error) {
        console.error('Failed to reset mock pipeline:', error);
      }
    }
    if (tracked) handledImportIds.current.add(tracked.id);
    clearTracking();
    setImportNotice(null);
    queryClient.removeQueries({ predicate: (query) => query.queryKey[0] !== 'me' });
    await queryClient.invalidateQueries({ queryKey: ['me'] });
  }, [clearTracking, queryClient, tracked]);

  const profile = me?.profile ?? EMPTY_PROFILE;

  /** Saves age range / sex, then refreshes everything compared against them. */
  const saveProfile = useCallback(async (update: Partial<UserProfile>) => {
    if (!sessionToken) throw new Error('Not logged in');
    const result = await updateProfile(sessionToken, update);
    queryClient.setQueriesData<MeResponse | null>({ queryKey: ['me', sessionToken] }, (current) => (
      current ? { ...current, profile: result.profile } : current
    ));
    await queryClient.invalidateQueries({
      predicate: (query) => ['population', 'riskReference'].includes(String(query.queryKey[0])),
    });
    return result.profile;
  }, [queryClient, sessionToken]);

  return {
    sessionToken,
    timeZone,
    phase,
    me,
    profile,
    saveProfile,
    meError: meQuery.error,
    refetchMe: meQuery.refetch,
    isRefreshingMe: meQuery.isFetching,
    datasets,
    readyPlatforms,
    dateBounds,
    boundsFor,
    pipelineStatus,
    importStatus,
    importPollError: tracked ? importQuery.error : null,
    isEnriching,
    notice,
    dismissNotice,
    resumeImportPolling,
    canResumeImport: !!tracked && pollingStopped,
    loginState,
    login,
    adoptGeneratedSession,
    logout,
    registerImport,
    resetConsole,
  };
}

export type ConsoleSession = ReturnType<typeof useConsoleSession>;
