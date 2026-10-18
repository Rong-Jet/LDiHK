import { useCallback, useEffect, useState } from 'react';
import { checkBackendHealth, isBackendMisconfigured, requestBackendWake, usesLocalMockApi } from '../lib/api';

export type BackendState = 'checking' | 'waking' | 'ready' | 'unreachable';

export interface BackendStatus {
  state: BackendState;
  isReady: boolean;
  /** Seconds since the current wake-up attempt started. */
  elapsedSeconds: number;
  /** Extra detail for the `unreachable` state. */
  message: string | null;
  retry: () => void;
}

/** Show the "waking the server" banner if /health has not answered after this long. */
export const WAKING_NOTICE_DELAY_MS = 3_000;
/** Give up (and offer a retry button) after roughly two minutes. */
export const BACKEND_WAKE_BUDGET_MS = 120_000;
const ATTEMPT_TIMEOUT_MS = 45_000;
const MAX_BACKOFF_MS = 10_000;
/** Ask the site's server to wake the backend at most this often while waiting. */
const WAKE_REPEAT_MS = 30_000;

function sleep(ms: number, signal: AbortSignal): Promise<void> {
  return new Promise((resolve) => {
    const timer = setTimeout(resolve, ms);
    signal.addEventListener('abort', () => {
      clearTimeout(timer);
      resolve();
    }, { once: true });
  });
}

/**
 * Pings `${PUBLIC_API_URL}/health` on mount and exposes the wake-up progress
 * so pages can gate their data queries on `isReady`. While the browser's own
 * request gets no answer, it also asks this site's /api/wake route, which
 * reaches the backend from the server side (and so starts a sleeping one).
 * When that route reaches it, the backend counts as ready even if this
 * browser's direct /health request keeps failing (a blocking extension or a
 * stale cache entry would otherwise leave the page waiting forever).
 */
export function useBackendStatus(): BackendStatus {
  const initialState: BackendState = usesLocalMockApi ? 'ready' : isBackendMisconfigured ? 'unreachable' : 'checking';
  const [state, setState] = useState<BackendState>(initialState);
  const [elapsedSeconds, setElapsedSeconds] = useState(0);
  const [attempt, setAttempt] = useState(0);

  useEffect(() => {
    if (usesLocalMockApi || isBackendMisconfigured) return;

    const controller = new AbortController();
    const startedAt = Date.now();
    let finished = false;

    setState('checking');
    setElapsedSeconds(0);

    let lastWakeAt = 0;
    const wake = () => {
      if (finished || Date.now() - lastWakeAt < WAKE_REPEAT_MS) return;
      lastWakeAt = Date.now();
      void requestBackendWake(controller.signal).then((awake) => {
        if (awake) stop('ready');
      });
    };

    const wakingTimer = setTimeout(() => {
      if (finished) return;
      setState((current) => (current === 'checking' ? 'waking' : current));
      wake();
    }, WAKING_NOTICE_DELAY_MS);
    const ticker = setInterval(() => {
      if (!finished) setElapsedSeconds(Math.round((Date.now() - startedAt) / 1000));
    }, 1000);

    const stop = (next: BackendState) => {
      if (finished) return;
      finished = true;
      clearTimeout(wakingTimer);
      clearInterval(ticker);
      if (!controller.signal.aborted) setState(next);
    };

    (async () => {
      let backoff = 1_000;
      while (!controller.signal.aborted && !finished) {
        const remaining = BACKEND_WAKE_BUDGET_MS - (Date.now() - startedAt);
        if (remaining <= 0) break;
        const healthy = await checkBackendHealth(controller.signal, Math.min(ATTEMPT_TIMEOUT_MS, remaining));
        if (controller.signal.aborted || finished) return;
        if (healthy) {
          stop('ready');
          return;
        }
        wake();
        const wait = Math.min(backoff, BACKEND_WAKE_BUDGET_MS - (Date.now() - startedAt));
        if (wait <= 0) break;
        await sleep(wait, controller.signal);
        backoff = Math.min(backoff * 2, MAX_BACKOFF_MS);
      }
      stop('unreachable');
    })();

    return () => {
      finished = true;
      controller.abort();
      clearTimeout(wakingTimer);
      clearInterval(ticker);
    };
  }, [attempt]);

  const retry = useCallback(() => setAttempt((value) => value + 1), []);

  return {
    state,
    isReady: state === 'ready',
    elapsedSeconds,
    message: isBackendMisconfigured
      ? 'No backend is configured. Set PUBLIC_API_URL (or PUBLIC_MOCK_API=true for local mock data) and rebuild.'
      : null,
    retry,
  };
}
