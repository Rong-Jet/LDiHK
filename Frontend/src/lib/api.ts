import { configuredBackendApiBase, isMockApiMode } from './env';

export { isMockApiMode };

export const backendApiBase = configuredBackendApiBase;

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
  query: () => backendApiUrl('/api/query'),
  imports: () => backendApiUrl('/api/imports'),
  importStatus: (importId: string) => backendApiUrl(`/api/imports/${encodeURIComponent(importId)}`),
  uploadUrl: () => localApiUrl('/api/upload-url'),
  uploaderInfo: () => localApiUrl('/api/uploader-info'),
  population: () => localApiUrl('/api/population'),
};
