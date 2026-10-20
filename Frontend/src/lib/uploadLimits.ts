/**
 * Server-side guards for the upload-signing function (/api/upload-url).
 *
 * The size cap matches the backend's MAX_IMPORT_ZIP_BYTES default, so an
 * archive the import worker would reject is refused before it is uploaded.
 * The rate limits live in the function instance's memory: Netlify may run
 * several instances, so they slow down scripted abuse rather than enforcing
 * an exact quota. The real cap is that every signed URL only accepts the
 * declared size.
 */

export const DEFAULT_MAX_UPLOAD_BYTES = 200 * 1024 * 1024;

export function maxUploadBytes(): number {
  const raw = (process.env.MAX_IMPORT_ZIP_BYTES ?? import.meta.env.MAX_IMPORT_ZIP_BYTES ?? '').toString().trim();
  const parsed = Number.parseInt(raw, 10);
  return Number.isFinite(parsed) && parsed > 0 ? parsed : DEFAULT_MAX_UPLOAD_BYTES;
}

/** Declared upload size in bytes, or an error code when it is unusable. */
export function parseUploadSize(value: unknown): { size: number } | { error: 'invalid_size' | 'file_too_large' } {
  if (typeof value !== 'number' || !Number.isInteger(value) || value <= 0) {
    return { error: 'invalid_size' };
  }
  if (value > maxUploadBytes()) return { error: 'file_too_large' };
  return { size: value };
}

interface Window {
  limit: number;
  windowMs: number;
}

export const SIGNING_LIMIT_PER_ID: Window = { limit: 30, windowMs: 60 * 60 * 1000 };
export const SIGNING_LIMIT_PER_IP: Window = { limit: 20, windowMs: 10 * 60 * 1000 };

const hits = new Map<string, number[]>();

/** Records a hit and returns the seconds to wait if `key` is over its limit. */
export function hitRateLimit(key: string, rule: Window, now: number = Date.now()): number | null {
  const recent = (hits.get(key) ?? []).filter((timestamp) => timestamp > now - rule.windowMs);
  if (recent.length >= rule.limit) {
    hits.set(key, recent);
    return Math.max(1, Math.ceil((recent[0] + rule.windowMs - now) / 1000));
  }
  recent.push(now);
  hits.set(key, recent);
  if (hits.size > 10_000) {
    for (const [entryKey, timestamps] of hits) {
      if (timestamps.every((timestamp) => timestamp <= now - rule.windowMs)) hits.delete(entryKey);
    }
  }
  return null;
}
