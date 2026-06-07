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
  : ((import.meta.env.PUBLIC_BACKEND_API_URL || import.meta.env.PUBLIC_API_URL || '') as string).replace(/\/+$/, '');
