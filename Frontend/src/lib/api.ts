import { configuredBackendApiBase, isBackendMisconfigured, isMockApiMode, usesLocalMockApi } from './env';
import { getBrowserTimeZone } from './dates';

export { isBackendMisconfigured, isMockApiMode, usesLocalMockApi };

export const backendApiBase = configuredBackendApiBase;

/** A sleeping free-tier Render instance can take ~60-90 s to answer the first request. */
export const BACKEND_REQUEST_TIMEOUT_MS = 90_000;

function normalizeApiPath(path: string): string {
  return path.startsWith('/') ? path : `/${path}`;
}

export function backendApiUrl(path: string): string {
  return `${backendApiBase}${normalizeApiPath(path)}`;
}

export function localApiUrl(path: string): string {
  return normalizeApiPath(path);
}

export function authHeaders(sessionToken: string | null | undefined): Record<string, string> {
  return sessionToken ? { Authorization: `Bearer ${sessionToken}` } : {};
}

export const jsonHeaders = {
  'Content-Type': 'application/json',
} as const;

export const apiRoutes = {
  health: () => backendApiUrl('/health'),
  me: (timeZone: string) => backendApiUrl(`/api/me?timezone=${encodeURIComponent(timeZone)}`),
  deleteMe: () => backendApiUrl('/api/me'),
  query: () => backendApiUrl('/api/query'),
  imports: () => backendApiUrl('/api/imports'),
  importStatus: (importId: string) => backendApiUrl(`/api/imports/${encodeURIComponent(importId)}`),
  // Called directly on the backend in live mode (no Netlify proxy); in mock mode
  // backendApiBase is empty, so this resolves to the local mock route.
  population: () => backendApiUrl('/api/population'),
  // Live uploads are signed by the backend, which enforces the storage budget;
  // the Astro route only serves the mock upload flow.
  uploadUrl: () => (usesLocalMockApi ? localApiUrl('/api/upload-url') : backendApiUrl('/api/uploads')),
  uploaderInfo: () => localApiUrl('/api/uploader-info'),
  wake: () => localApiUrl('/api/wake'),
};

// ---------------------------------------------------------------------------
// Errors
// ---------------------------------------------------------------------------

export type ApiErrorKind = 'http' | 'network' | 'timeout';

export class ApiError extends Error {
  readonly status: number;
  readonly code: string | null;
  readonly kind: ApiErrorKind;

  constructor(message: string, options: { status?: number; code?: string | null; kind: ApiErrorKind }) {
    super(message);
    this.name = 'ApiError';
    this.status = options.status ?? 0;
    this.code = options.code ?? null;
    this.kind = options.kind;
  }
}

/** Network failures, timeouts, 429 and 5xx are worth retrying; other 4xx are not. */
export function isRetryableApiError(error: unknown): boolean {
  if (!(error instanceof ApiError)) return false;
  if (error.kind !== 'http') return true;
  return error.status === 429 || error.status >= 500;
}

export function isApiStatus(error: unknown, ...statuses: number[]): boolean {
  return error instanceof ApiError && statuses.includes(error.status);
}

const ERROR_CODE_MESSAGES: Record<string, string> = {
  database_unavailable: 'The database is temporarily unavailable. Please try again in a moment.',
  unknown_ldihk_id: 'No dashboard found for this ID.',
  invalid_timezone: 'Your browser timezone was rejected by the server.',
  import_not_found: 'This import could not be found.',
  unauthorized_import: 'This import belongs to a different LDiHK-ID.',
  missing_authorization: 'Missing LDiHK-ID. Please log in again.',
  invalid_authorization: 'This LDiHK-ID is not valid. Please log in again.',
  backend_not_configured: 'The analytics backend is not configured (PUBLIC_API_URL).',
  unsupported_platform: 'Population benchmarks currently support YouTube only.',
  rate_limited: 'Too many requests in a short time. Please wait a few minutes and try again.',
  confirmation_mismatch: 'The ID you typed does not match your LDiHK-ID.',
  file_too_large: 'The archive is too large. Export only your history files and try again.',
  upload_storage_full: 'Too many archives are waiting to be processed. Please try again in an hour.',
  upload_budget_exhausted: "This month's upload limit is reached. Uploads open again on the 1st of next month.",
  uploads_disabled: 'Uploads are switched off at the moment. Please try again later.',
};

export function describeApiError(error: unknown, fallback = 'Something went wrong while talking to the server.'): string {
  if (error instanceof ApiError) {
    if (error.kind === 'timeout') {
      return 'The server took too long to respond. It may still be waking up on the free tier. Please retry.';
    }
    if (error.kind === 'network') {
      return 'Could not reach the server. Check your connection; on the free tier the server may be waking up. Please retry.';
    }
    if (error.code && ERROR_CODE_MESSAGES[error.code]) return ERROR_CODE_MESSAGES[error.code];
    if (error.status === 503) return ERROR_CODE_MESSAGES.database_unavailable;
    if (error.status >= 500) return `The server reported an error (HTTP ${error.status}). Please retry.`;
    return error.message || fallback;
  }
  if (error instanceof Error && error.message) return error.message;
  return fallback;
}

// ---------------------------------------------------------------------------
// Fetch helper
// ---------------------------------------------------------------------------

function combineSignals(external: AbortSignal | undefined, timeoutMs: number) {
  const timeout = AbortSignal.timeout(timeoutMs);
  if (!external) return { signal: timeout, timeout };
  if (typeof AbortSignal.any === 'function') {
    return { signal: AbortSignal.any([external, timeout]), timeout };
  }
  const controller = new AbortController();
  const abort = () => controller.abort();
  if (external.aborted || timeout.aborted) controller.abort();
  external.addEventListener('abort', abort, { once: true });
  timeout.addEventListener('abort', abort, { once: true });
  return { signal: controller.signal, timeout };
}

async function readErrorBody(response: Response): Promise<{ code: string | null; message: string | null }> {
  try {
    const text = await response.text();
    if (!text) return { code: null, message: null };
    try {
      const parsed = JSON.parse(text);
      const code = typeof parsed?.error === 'string' ? parsed.error : null;
      const message = typeof parsed?.message === 'string' ? parsed.message : null;
      return { code, message };
    } catch {
      return { code: null, message: text.slice(0, 200) };
    }
  } catch {
    return { code: null, message: null };
  }
}

export interface ApiRequestOptions {
  method?: 'GET' | 'POST' | 'PUT' | 'DELETE';
  token?: string | null;
  body?: unknown;
  signal?: AbortSignal;
  timeoutMs?: number;
}

/**
 * JSON fetch with a 90 s timeout. Throws `ApiError` for network failures,
 * timeouts and non-2xx responses (parsing `{"error": ...}` when present) so
 * callers never mistake a failure for an empty result.
 */
export async function apiFetchJson<T>(url: string, options: ApiRequestOptions = {}): Promise<T> {
  const { signal, timeout } = combineSignals(options.signal, options.timeoutMs ?? BACKEND_REQUEST_TIMEOUT_MS);
  const headers: Record<string, string> = { ...authHeaders(options.token) };
  if (options.body !== undefined) headers['Content-Type'] = 'application/json';

  let response: Response;
  try {
    response = await fetch(url, {
      method: options.method ?? (options.body !== undefined ? 'POST' : 'GET'),
      headers,
      body: options.body !== undefined ? JSON.stringify(options.body) : undefined,
      signal,
      // Never answer from the browser cache: a stored response would hide
      // the live backend.
      cache: 'no-store',
    });
  } catch (error) {
    if (timeout.aborted) {
      throw new ApiError('Request timed out', { kind: 'timeout' });
    }
    if (options.signal?.aborted) throw error; // caller cancelled; let react-query handle it
    throw new ApiError(error instanceof Error ? error.message : 'Network request failed', { kind: 'network' });
  }

  if (!response.ok) {
    const { code, message } = await readErrorBody(response);
    throw new ApiError(message || code || `HTTP ${response.status}`, { status: response.status, code, kind: 'http' });
  }

  try {
    return (await response.json()) as T;
  } catch {
    throw new ApiError('The server returned an unreadable response.', { status: response.status, kind: 'http' });
  }
}

// ---------------------------------------------------------------------------
// Backend contract types and calls
// ---------------------------------------------------------------------------

export type ImportState = 'queued' | 'running' | 'completed' | 'failed';
/** `unavailable`: no YouTube API key is configured, durations stay estimated. */
export type EnrichmentState = 'queued' | 'running' | 'completed' | 'failed' | 'unavailable' | null;

export interface ImportStatus {
  import_id: string;
  ldihk_id: string;
  status: ImportState;
  records_seen: number | null;
  records_imported: number | null;
  warnings_count: number | null;
  error_message: string | null;
  created_at: string | null;
  started_at: string | null;
  finished_at: string | null;
  enrichment_status?: EnrichmentState;
  enrichment_started_at?: string | null;
  enrichment_finished_at?: string | null;
}

export interface DatasetSummary {
  event_count: number;
  watch_event_count: number;
  first_event_at: string | null;
  last_event_at: string | null;
  /** YYYY-MM-DD in the timezone requested from /api/me. */
  min_date: string | null;
  max_date: string | null;
}

export interface MeResponse {
  ldihk_id: string;
  exists: boolean;
  timezone: string;
  datasets: Record<string, DatasetSummary>;
  latest_import: ImportStatus | null;
}

export type QueryDataset = 'youtube_usage' | 'tiktok_usage' | 'instagram_usage' | 'usage_analytics' | `${string}_usage`;

export interface QueryRequest {
  dataset: QueryDataset;
  metrics: string[];
  dimensions: string[];
  filters?: Record<string, unknown>;
  options?: {
    include_zero_buckets?: boolean;
    limit?: number;
    sort_by?: string;
    sort_direction?: 'asc' | 'desc';
    timezone?: string;
  };
}

export interface QueryResponse<Row> {
  rows: Row[];
  [key: string]: unknown;
}

/** Backend maximum for `options.limit`. */
export const QUERY_LIMIT_MAX = 10_000;

export function isPendingEnrichment(importStatus: ImportStatus | null | undefined): boolean {
  return importStatus?.status === 'completed'
    && (importStatus.enrichment_status === 'queued' || importStatus.enrichment_status === 'running');
}

export function isImportInFlight(importStatus: ImportStatus | null | undefined): boolean {
  return importStatus?.status === 'queued' || importStatus?.status === 'running';
}

export async function checkBackendHealth(signal: AbortSignal, timeoutMs: number): Promise<boolean> {
  try {
    const body = await apiFetchJson<{ status?: string }>(apiRoutes.health(), { signal, timeoutMs });
    return body?.status === 'ok';
  } catch {
    return false;
  }
}

/**
 * Asks this site's server to reach the backend (see pages/api/wake.ts), which
 * also starts a sleeping one. True when the backend answered. Never throws.
 */
export async function requestBackendWake(signal: AbortSignal): Promise<boolean> {
  try {
    const response = await fetch(apiRoutes.wake(), { signal, cache: 'no-store' });
    const body = response.ok ? await response.json() : null;
    return body?.status === 'ok';
  } catch {
    return false;
  }
}

export function fetchMe(token: string, timeZone: string, signal?: AbortSignal): Promise<MeResponse> {
  return apiFetchJson<MeResponse>(apiRoutes.me(timeZone), { token, signal });
}

/** POST /api/query. Always sends the browser timezone unless one is given. */
export function postQuery<Row>(token: string, request: QueryRequest, signal?: AbortSignal): Promise<QueryResponse<Row>> {
  const limit = request.options?.limit;
  return apiFetchJson<QueryResponse<Row>>(apiRoutes.query(), {
    token,
    signal,
    body: {
      ...request,
      options: {
        ...request.options,
        ...(limit !== undefined ? { limit: Math.min(QUERY_LIMIT_MAX, Math.max(1, Math.ceil(limit))) } : {}),
        timezone: request.options?.timezone ?? getBrowserTimeZone(),
      },
    },
  });
}

export function fetchImportStatus(token: string, importId: string, signal?: AbortSignal): Promise<ImportStatus> {
  return apiFetchJson<ImportStatus>(apiRoutes.importStatus(importId), { token, signal });
}

export interface CreateImportPayload {
  s3_bucket: string;
  s3_key: string;
  s3_etag?: string;
  age?: number;
  sex?: string;
}

export function createImport(token: string, payload: CreateImportPayload): Promise<{ import_id: string; ldihk_id: string; status: ImportState }> {
  return apiFetchJson(apiRoutes.imports(), { token, body: payload });
}

export interface DeleteMyDataResponse {
  deleted: boolean;
  events_deleted: number;
  imports_deleted: number;
  uploads_deleted: number | null;
}

/** DELETE /api/me: erases the account and all its data. `confirm` must equal the ID. */
export function deleteMyData(token: string, confirm: string): Promise<DeleteMyDataResponse> {
  return apiFetchJson<DeleteMyDataResponse>(apiRoutes.deleteMe(), { token, method: 'DELETE', body: { confirm } });
}

export function fetchPopulationJson<T>(token: string, payload: Record<string, unknown>, signal?: AbortSignal): Promise<T> {
  return apiFetchJson<T>(apiRoutes.population(), { token, body: payload, signal });
}
