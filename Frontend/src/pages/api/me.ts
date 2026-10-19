import type { APIRoute } from 'astro';
import fs from 'fs/promises';
import path from 'path';
import os from 'os';
import { isMockApiMode, usesLocalMockApi } from '../../lib/env';
import { isValidLdihkId } from '../../lib/ldihkId';

export const prerender = false;

// Local mock of the backend's GET /api/me (only used in mock mode, where the
// browser talks to these Astro routes instead of the Flask backend).
const MOCK_PLATFORMS = ['youtube', 'instagram', 'tiktok', 'spotify'];
const MOCK_MIN_DATE = '2016-06-07';
const MOCK_MAX_DATE = '2026-06-06';

const JSON_HEADERS = {
  'Content-Type': 'application/json',
  'Access-Control-Allow-Origin': '*',
};

function json(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), { status, headers: JSON_HEADERS });
}

function mockSummary(minDate: string, maxDate: string) {
  // Non-zero counts: the console treats a platform as ready only when it
  // has events (the mock query routes simulate the actual numbers).
  return {
    event_count: 1000,
    watch_event_count: 1000,
    first_event_at: `${minDate}T00:00:00+00:00`,
    last_event_at: `${maxDate}T23:59:59+00:00`,
    min_date: minDate,
    max_date: maxDate,
    watch_min_date: minDate,
    watch_max_date: maxDate,
  };
}

export const OPTIONS: APIRoute = async () => {
  return new Response(null, {
    status: 204,
    headers: {
      'Access-Control-Allow-Origin': '*',
      'Access-Control-Allow-Methods': 'GET, DELETE, OPTIONS',
      'Access-Control-Allow-Headers': 'Content-Type, Authorization',
      'Access-Control-Max-Age': '86400',
    },
  });
};

export const GET: APIRoute = async ({ request, url }) => {
  if (!usesLocalMockApi) {
    return json({ error: 'backend_not_configured' }, 503);
  }

  const authHeader = request.headers.get('Authorization') || '';
  if (!authHeader.startsWith('Bearer ')) {
    return json({ error: 'missing_authorization' }, 401);
  }
  const ldihkId = authHeader.slice('Bearer '.length).trim();
  if (!isValidLdihkId(ldihkId)) {
    return json({ error: 'invalid_authorization' }, 401);
  }

  let state: any = { datasets: {}, imports: {} };
  try {
    state = JSON.parse(await fs.readFile(path.join(os.tmpdir(), 'ldihk_state.json'), 'utf-8'));
  } catch {
    // No mock state yet.
  }

  const datasets: Record<string, ReturnType<typeof mockSummary>> = {};
  if (isMockApiMode) {
    for (const platform of MOCK_PLATFORMS) {
      datasets[platform] = mockSummary(MOCK_MIN_DATE, MOCK_MAX_DATE);
    }
  } else {
    for (const [platform, dataset] of Object.entries<any>(state.datasets ?? {})) {
      if (dataset?.status === 'READY') {
        datasets[platform] = mockSummary(dataset.min_date || MOCK_MIN_DATE, dataset.max_date || MOCK_MAX_DATE);
      }
    }
  }

  const userImports = Object.values<any>(state.imports ?? {})
    .filter((record) => record?.ldihk_id === ldihkId)
    .sort((a, b) => String(b.created_at).localeCompare(String(a.created_at)));
  const latestImport = userImports[0] ?? null;

  if (Object.keys(datasets).length === 0 && !latestImport) {
    return json({ error: 'unknown_ldihk_id' }, 404);
  }

  return json({
    ldihk_id: ldihkId,
    exists: true,
    timezone: url.searchParams.get('timezone') || 'UTC',
    datasets,
    latest_import: latestImport
      ? { enrichment_status: null, enrichment_started_at: null, enrichment_finished_at: null, ...latestImport }
      : null,
  });
};

// Mock of DELETE /api/me: forgets this ID's simulated imports.
export const DELETE: APIRoute = async ({ request }) => {
  if (!usesLocalMockApi) {
    return json({ error: 'backend_not_configured' }, 503);
  }
  const authHeader = request.headers.get('Authorization') || '';
  const ldihkId = authHeader.startsWith('Bearer ') ? authHeader.slice('Bearer '.length).trim() : '';
  if (!isValidLdihkId(ldihkId)) {
    return json({ error: 'invalid_authorization' }, 401);
  }
  let body: any = null;
  try {
    body = await request.json();
  } catch {
    // Missing body is a confirmation mismatch below.
  }
  if (body?.confirm !== ldihkId) {
    return json({ error: 'confirmation_mismatch' }, 400);
  }

  const statePath = path.join(os.tmpdir(), 'ldihk_state.json');
  let state: any = { datasets: {}, imports: {} };
  try {
    state = JSON.parse(await fs.readFile(statePath, 'utf-8'));
  } catch {
    // No mock state yet.
  }
  let importsDeleted = 0;
  for (const [importId, record] of Object.entries<any>(state.imports ?? {})) {
    if (record?.ldihk_id === ldihkId) {
      delete state.imports[importId];
      importsDeleted += 1;
    }
  }
  try {
    await fs.writeFile(statePath, JSON.stringify(state, null, 2));
  } catch (error) {
    console.error('Failed to update mock state:', error);
  }
  return json({ deleted: true, events_deleted: 0, imports_deleted: importsDeleted, subscriptions_deleted: 0, uploads_deleted: null });
};
