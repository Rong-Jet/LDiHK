import React, { createContext, useCallback, useContext, useEffect, useMemo, useRef, useState } from 'react';
import { apiRoutes, authHeaders, jsonHeaders, type UserProfile } from '../lib/api';
// zip.js is loaded on demand (only for large archives), not with every page.
const SLIM_THRESHOLD_BYTES = 20 * 1024 * 1024;

/** Largest archive we upload (after trimming). */
export const MAX_UPLOAD_BYTES = 200 * 1024 * 1024;
const UPLOAD_TIMEOUT_MS = 30 * 60 * 1000;

export type UploadPhase = 'IDLE' | 'SLIMMING' | 'UPLOADING' | 'REGISTERING' | 'SUCCESS' | 'ERROR';

export interface UploadState {
  phase: UploadPhase;
  /** 0-100 for SLIMMING and UPLOADING. */
  progress: number;
  fileName: string;
  originalSize: number;
  uploadSize: number;
  /** Human-readable note about archive trimming (what was removed, or why it was skipped). */
  slimNote: string | null;
  errorMessage: string;
}

export interface UploadController extends UploadState {
  isBusy: boolean;
  /** `true` when the Astro helper will use the local mock upload route. */
  isMock: boolean | null;
  /** `profile`: optional age range / sex, stored with the import (first upload). */
  start: (file: File, sessionToken: string, profile?: UserProfile) => void;
  cancel: () => void;
  reset: () => void;
}

type UploadCompleteHandler = (s3Key: string, s3Bucket: string, sessionToken: string, profile?: UserProfile) => Promise<void> | void;

const INITIAL_STATE: UploadState = {
  phase: 'IDLE',
  progress: 0,
  fileName: '',
  originalSize: 0,
  uploadSize: 0,
  slimNote: null,
  errorMessage: '',
};

export function formatFileSize(bytes: number): string {
  if (!bytes) return '0 Bytes';
  const k = 1024;
  const sizes = ['Bytes', 'KB', 'MB', 'GB'];
  const i = Math.min(sizes.length - 1, Math.floor(Math.log(bytes) / Math.log(k)));
  return `${parseFloat((bytes / Math.pow(k, i)).toFixed(2))} ${sizes[i]}`;
}

class UploadAbortedError extends Error {
  constructor() {
    super('Upload aborted');
    this.name = 'AbortError';
  }
}

/** Extracts `<Code>`/`<Message>` from an S3/R2 XML error, else a short body snippet. */
function describeStorageError(status: number, body: string): string {
  const code = body.match(/<Code>([^<]*)<\/Code>/)?.[1];
  const message = body.match(/<Message>([^<]*)<\/Message>/)?.[1];
  const detail = code
    ? `${code}${message ? `: ${message}` : ''}`
    : body.replace(/\s+/g, ' ').trim().slice(0, 200);
  return `Storage rejected the upload (HTTP ${status}${detail ? ` - ${detail}` : ''}).`;
}

function safeUploadName(file: File): string {
  const name = (file.name || 'export.zip').trim();
  return /\.zip$/i.test(name) ? name : `${name}.zip`;
}

function putWithProgress(
  url: string,
  method: string,
  headers: Record<string, string> | undefined,
  body: Blob,
  signal: AbortSignal,
  onProgress: (percent: number) => void
): Promise<void> {
  return new Promise((resolve, reject) => {
    const xhr = new XMLHttpRequest();
    xhr.open(method || 'PUT', url, true);
    Object.entries(headers ?? {}).forEach(([key, value]) => xhr.setRequestHeader(key, String(value)));
    xhr.timeout = UPLOAD_TIMEOUT_MS;
    xhr.upload.onprogress = (event) => {
      if (event.lengthComputable) onProgress(Math.round((event.loaded / event.total) * 100));
    };
    xhr.onload = () => {
      if (xhr.status >= 200 && xhr.status < 300) resolve();
      else reject(new Error(describeStorageError(xhr.status, xhr.responseText || '')));
    };
    xhr.onerror = () => reject(new Error(
      'The upload to storage failed before the server answered (network error, or the bucket CORS policy blocked this site). Check your connection and try again.'
    ));
    xhr.ontimeout = () => reject(new Error('The upload timed out after 30 minutes. Please try again on a faster connection.'));
    xhr.onabort = () => reject(new UploadAbortedError());
    signal.addEventListener('abort', () => xhr.abort(), { once: true });
    xhr.send(body);
  });
}

async function requestUploadTarget(file: Blob, fileName: string, token: string) {
  const response = await fetch(apiRoutes.uploadUrl(), {
    method: 'POST',
    headers: { ...jsonHeaders, ...authHeaders(token) },
    body: JSON.stringify({ filename: fileName, contentType: 'application/zip', size: file.size }),
  });
  const payload = await response.json().catch(() => null);
  if (!response.ok) {
    const detail = typeof payload?.message === 'string' ? payload.message : typeof payload?.error === 'string' ? payload.error : `HTTP ${response.status}`;
    throw new Error(`Could not prepare the upload: ${detail}`);
  }
  if (!payload?.url || !payload?.s3Key || !payload?.s3Bucket) {
    throw new Error('Could not prepare the upload: the upload helper returned an incomplete response.');
  }
  return payload as {
    url: string;
    method?: string;
    headers?: Record<string, string>;
    s3Bucket: string;
    s3Key: string;
    isMock?: boolean;
  };
}

const UploadContext = createContext<UploadController | null>(null);

/**
 * Owns the upload lifecycle above the page layout, so a running upload keeps
 * its progress/error state when the layout switches (e.g. the login screen is
 * replaced by the dashboard right after a new LDiHK-ID is generated). Every
 * <UploadZone> renders this shared state; only one upload can run at a time.
 */
export function UploadProvider({ onUploadComplete, children }: { onUploadComplete: UploadCompleteHandler; children: React.ReactNode }) {
  const [state, setState] = useState<UploadState>(INITIAL_STATE);
  const [isMock, setIsMock] = useState<boolean | null>(null);
  const busyRef = useRef(false);
  const abortRef = useRef<AbortController | null>(null);
  const onCompleteRef = useRef(onUploadComplete);
  onCompleteRef.current = onUploadComplete;

  useEffect(() => {
    let cancelled = false;
    fetch(apiRoutes.uploaderInfo())
      .then((res) => (res.ok ? res.json() : Promise.reject(new Error(`HTTP ${res.status}`))))
      .then((data) => {
        if (!cancelled) setIsMock(typeof data?.isMock === 'boolean' ? data.isMock : null);
      })
      .catch((err) => console.error('Failed to retrieve uploader info:', err));
    return () => {
      cancelled = true;
    };
  }, []);

  const patch = useCallback((next: Partial<UploadState>) => setState((current) => ({ ...current, ...next })), []);

  const start = useCallback((file: File, sessionToken: string, profile?: UserProfile) => {
    if (busyRef.current) return; // prevent double uploads
    busyRef.current = true;
    const controller = new AbortController();
    abortRef.current = controller;
    const { signal } = controller;

    setState({ ...INITIAL_STATE, phase: 'UPLOADING', fileName: file.name, originalSize: file.size, uploadSize: file.size });

    (async () => {
      try {
        if (!/\.zip$/i.test(file.name)) throw new Error('Only ZIP files (.zip) are supported.');

        let payload: Blob = file;
        if (file.size > SLIM_THRESHOLD_BYTES) {
          patch({ phase: 'SLIMMING', progress: 0 });
          try {
            const { slimZipArchive } = await import('../lib/slimZip');
            const slimmed = await slimZipArchive(file, {
              signal,
              onProgress: (fraction) => patch({ progress: Math.round(fraction * 100) }),
            });
            if (slimmed && slimmed.slimmedBytes < file.size) {
              payload = slimmed.blob;
              patch({
                slimNote: `Removed ${slimmed.removedEntries} video/photo/audio file${slimmed.removedEntries === 1 ? '' : 's'} (${formatFileSize(file.size)} -> ${formatFileSize(slimmed.slimmedBytes)}).`,
              });
            } else {
              patch({ slimNote: 'No videos or photos to remove; uploading the original archive.' });
            }
          } catch (error) {
            if (signal.aborted) throw new UploadAbortedError();
            console.warn('Archive trimming failed, uploading the original archive instead:', error);
            payload = file;
            patch({ slimNote: 'Could not read this archive to trim it; uploading the original file.' });
          }
        }

        if (payload.size > MAX_UPLOAD_BYTES) {
          throw new Error(
            `This archive is ${formatFileSize(payload.size)}${payload !== file ? ' even after removing videos and photos' : ''}. `
            + `The maximum upload size is ${formatFileSize(MAX_UPLOAD_BYTES)}. Please export only your watch/activity history and try again.`
          );
        }

        patch({ phase: 'UPLOADING', progress: 0, uploadSize: payload.size });
        const target = await requestUploadTarget(payload, safeUploadName(file), sessionToken);
        if (typeof target.isMock === 'boolean') setIsMock(target.isMock);
        if (signal.aborted) throw new UploadAbortedError();

        await putWithProgress(target.url, target.method || 'PUT', target.headers, payload, signal, (progress) => patch({ progress }));

        patch({ phase: 'REGISTERING', progress: 100 });
        try {
          await onCompleteRef.current(target.s3Key, target.s3Bucket, sessionToken, profile);
        } catch (error) {
          const detail = error instanceof Error && error.message ? error.message : 'unknown error';
          throw new Error(`The archive was uploaded, but registering the import failed: ${detail}`);
        }
        patch({ phase: 'SUCCESS', progress: 100 });
      } catch (error) {
        if (signal.aborted || (error instanceof Error && error.name === 'AbortError')) {
          setState(INITIAL_STATE);
        } else {
          console.error('Upload failed:', error);
          patch({
            phase: 'ERROR',
            errorMessage: error instanceof Error && error.message ? error.message : 'An unexpected error occurred during upload.',
          });
        }
      } finally {
        busyRef.current = false;
        abortRef.current = null;
      }
    })();
  }, [patch]);

  const cancel = useCallback(() => {
    abortRef.current?.abort();
  }, []);

  const reset = useCallback(() => {
    if (!busyRef.current) setState(INITIAL_STATE);
  }, []);

  const value = useMemo<UploadController>(() => ({
    ...state,
    isBusy: state.phase === 'SLIMMING' || state.phase === 'UPLOADING' || state.phase === 'REGISTERING',
    isMock,
    start,
    cancel,
    reset,
  }), [state, isMock, start, cancel, reset]);

  return <UploadContext.Provider value={value}>{children}</UploadContext.Provider>;
}

export function useUploadController(): UploadController {
  const controller = useContext(UploadContext);
  if (!controller) throw new Error('useUploadController must be used inside <UploadProvider>.');
  return controller;
}
