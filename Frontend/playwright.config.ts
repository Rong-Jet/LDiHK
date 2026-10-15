import { defineConfig, devices } from '@playwright/test';

/**
 * Browser end-to-end tests against the one-command local stack
 * (scripts/dev_stack.py): real Postgres, local S3 stand-in, API with workers.
 * Nothing here talks to hosted services.
 *
 *   npm run test:e2e                       starts a fresh stack, runs, stops it
 *   E2E_BASE_URL=http://localhost:4321 npm run test:e2e   use a running stack
 */
const externalStack = Boolean(process.env.E2E_BASE_URL);

export default defineConfig({
  testDir: './e2e',
  timeout: 180_000,
  expect: { timeout: 20_000 },
  // One stack, one database: run the flows one after another.
  workers: 1,
  fullyParallel: false,
  retries: process.env.CI ? 1 : 0,
  reporter: process.env.CI ? [['list'], ['html', { open: 'never' }]] : 'list',
  use: {
    ...devices['Desktop Chrome'],
    baseURL: process.env.E2E_BASE_URL ?? 'http://localhost:4321',
    trace: 'retain-on-failure',
    screenshot: 'only-on-failure',
  },
  webServer: externalStack
    ? undefined
    : {
        command: 'uv run python scripts/dev_stack.py --fresh',
        cwd: '..',
        url: 'http://localhost:4321/',
        // The first run downloads Python 3.12 and the local service packages.
        timeout: 600_000,
        reuseExistingServer: !process.env.CI,
        stdout: 'pipe',
        stderr: 'pipe',
      },
});
