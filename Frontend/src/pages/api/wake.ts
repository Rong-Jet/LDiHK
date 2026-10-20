import type { APIRoute } from 'astro';
import { configuredBackendApiBase, usesLocalMockApi } from '../../lib/env';

export const prerender = false;

/** How long this function waits for the backend before answering "waking". */
const WAKE_WAIT_MS = 8_000;

function json(body: object, status: number) {
  return new Response(JSON.stringify(body), {
    status,
    headers: { 'Content-Type': 'application/json', 'Cache-Control': 'no-store' },
  });
}

// Reaches the backend from the server side while a browser's own /health
// request gets no answer, and so also starts a sleeping free-tier backend
// (Render holds the request until the service is up). Console pages call it
// while they wait and treat "ok" as ready, so a browser whose direct request
// is blocked (an extension, a stale cache entry) is not left waiting forever.
// Same origin only, fixed URL, no parameters.
export const GET: APIRoute = async () => {
  if (usesLocalMockApi || !configuredBackendApiBase) {
    return json({ status: 'ok' }, 200);
  }
  try {
    const response = await fetch(`${configuredBackendApiBase}/health`, {
      signal: AbortSignal.timeout(WAKE_WAIT_MS),
    });
    return response.ok ? json({ status: 'ok' }, 200) : json({ status: 'waking' }, 202);
  } catch {
    // Timed out or refused: the wake-up was still triggered.
    return json({ status: 'waking' }, 202);
  }
};
