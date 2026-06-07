import type { APIRoute } from 'astro';
import fs from 'fs/promises';
import path from 'path';
import os from 'os';

export const prerender = false;

// Handle OPTIONS preflight requests for CORS compatibility
export const OPTIONS: APIRoute = async () => {
  return new Response(null, {
    status: 204,
    headers: {
      'Access-Control-Allow-Origin': '*',
      'Access-Control-Allow-Methods': 'GET, OPTIONS',
      'Access-Control-Allow-Headers': 'Content-Type, Authorization',
      'Access-Control-Max-Age': '86400',
    },
  });
};

export const GET: APIRoute = async ({ params, request }) => {
  const authHeader = request.headers.get('Authorization') || '';
  if (!authHeader.startsWith('Bearer ')) {
    return new Response(JSON.stringify({ error: 'missing_authorization' }), {
      status: 401,
      headers: { 'Content-Type': 'application/json', 'Access-Control-Allow-Origin': '*' },
    });
  }

  const ldihkId = authHeader.replace('Bearer ', '').trim();
  if (!ldihkId) {
    return new Response(JSON.stringify({ error: 'invalid_authorization' }), {
      status: 401,
      headers: { 'Content-Type': 'application/json', 'Access-Control-Allow-Origin': '*' },
    });
  }

  const importId = params.id;
  if (!importId) {
    return new Response(JSON.stringify({ error: 'import_not_found' }), {
      status: 404,
      headers: { 'Content-Type': 'application/json', 'Access-Control-Allow-Origin': '*' },
    });
  }

  const statePath = path.join(os.tmpdir(), 'ldihk_state.json');
  let state: any = { datasets: {}, imports: {} };

  try {
    const data = await fs.readFile(statePath, 'utf-8');
    state = JSON.parse(data);
  } catch (err) {
    return new Response(JSON.stringify({ error: 'import_not_found' }), {
      status: 404,
      headers: { 'Content-Type': 'application/json', 'Access-Control-Allow-Origin': '*' },
    });
  }

  if (!state.imports || !state.imports[importId]) {
    return new Response(JSON.stringify({ error: 'import_not_found' }), {
      status: 404,
      headers: { 'Content-Type': 'application/json', 'Access-Control-Allow-Origin': '*' },
    });
  }

  const record = state.imports[importId];

  // Enforce identity scope check
  if (record.ldihk_id !== ldihkId) {
    return new Response(JSON.stringify({ error: 'unauthorized_import' }), {
      status: 403,
      headers: { 'Content-Type': 'application/json', 'Access-Control-Allow-Origin': '*' },
    });
  }

  // Simulate worker lifecycle progress
  const nowMs = Date.now();
  const createdMs = new Date(record.created_at).getTime();
  const elapsedFromCreation = nowMs - createdMs;

  let stateUpdated = false;

  if (record.status === 'queued') {
    if (elapsedFromCreation >= 2000) { // transition to running after 2 seconds
      record.status = 'running';
      record.started_at = new Date().toISOString();
      stateUpdated = true;
    }
  }

  if (record.status === 'running') {
    const startedMs = new Date(record.started_at || record.created_at).getTime();
    const elapsedFromStart = nowMs - startedMs;

    if (elapsedFromStart >= 3000) { // transition to completed after 3 seconds
      record.status = 'completed';
      record.finished_at = new Date().toISOString();
      record.records_seen = 240;
      record.records_imported = 238;
      record.warnings_count = 2;
      
      // Update global datasets state for youtube
      state.datasets.youtube = {
        status: 'READY',
        min_date: '2026-05-08',
        max_date: '2026-06-06',
      };
      
      stateUpdated = true;
    } else {
      // Scale records incrementally while running
      const progressRatio = Math.max(0.1, Math.min(0.95, elapsedFromStart / 3000));
      record.records_seen = Math.round(progressRatio * 240);
      record.records_imported = Math.round(progressRatio * 238);
      record.warnings_count = Math.round(progressRatio * 2);
    }
  }

  if (stateUpdated) {
    try {
      await fs.writeFile(statePath, JSON.stringify(state, null, 2));
    } catch (writeErr) {
      console.error('Failed to save updated import state:', writeErr);
    }
  }

  return new Response(JSON.stringify(record), {
    status: 200,
    headers: {
      'Content-Type': 'application/json',
      'Access-Control-Allow-Origin': '*',
    },
  });
};
