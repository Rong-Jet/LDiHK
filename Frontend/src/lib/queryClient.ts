import { QueryClient } from '@tanstack/react-query';
import { isRetryableApiError } from './api';

/**
 * Shared react-query defaults for the console pages: retry network failures,
 * timeouts and 5xx (e.g. a waking Render instance or `database_unavailable`)
 * with exponential backoff, but never retry 4xx responses.
 */
export function createConsoleQueryClient(): QueryClient {
  return new QueryClient({
    defaultOptions: {
      queries: {
        refetchOnWindowFocus: false,
        retry: (failureCount, error) => isRetryableApiError(error) && failureCount < 3,
        retryDelay: (attempt) => Math.min(2000 * 2 ** attempt, 15_000),
      },
    },
  });
}
