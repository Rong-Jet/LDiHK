const TRUTHY_ENV_VALUES = new Set(['1', 'true', 'yes', 'on']);

function readEnvString(value: unknown): string | null {
  if (typeof value !== 'string') return null;
  const trimmed = value.trim();
  return trimmed.length > 0 ? trimmed.toLowerCase() : null;
}

const publicMockApiValue = readEnvString(import.meta.env.PUBLIC_MOCK_API);

export const isMockApiMode = publicMockApiValue !== null && TRUTHY_ENV_VALUES.has(publicMockApiValue);
export const shouldAllowImplicitMockApiMode = publicMockApiValue === null;

export const configuredBackendApiBase = isMockApiMode
  ? ''
  : ((import.meta.env.PUBLIC_API_URL || '') as string).trim().replace(/\/+$/, '');

/**
 * True when browser API calls are answered by the local Astro mock routes
 * (explicit `PUBLIC_MOCK_API=true`, or legacy implicit fallback when neither
 * `PUBLIC_MOCK_API` nor `PUBLIC_API_URL` is set). The UI labels this as mock
 * data so simulated numbers are never presented as real.
 */
export const usesLocalMockApi = isMockApiMode || (!configuredBackendApiBase && shouldAllowImplicitMockApiMode);

/** Live mode was requested (`PUBLIC_MOCK_API=false`) but no backend origin is configured. */
export const isBackendMisconfigured = !usesLocalMockApi && !configuredBackendApiBase;
