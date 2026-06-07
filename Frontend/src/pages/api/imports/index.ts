import type { APIRoute } from 'astro';
import fs from 'fs/promises';
import path from 'path';
import os from 'os';
import crypto from 'crypto';

export const prerender = false;

// Handle OPTIONS preflight requests for CORS compatibility
export const OPTIONS: APIRoute = async () => {
  return new Response(null, {
    status: 204,
    headers: {
      'Access-Control-Allow-Origin': '*',
      'Access-Control-Allow-Methods': 'POST, OPTIONS',
      'Access-Control-Allow-Headers': 'Content-Type, Authorization',
      'Access-Control-Max-Age': '86400',
    },
  });
};

export const POST: APIRoute = async ({ request }) => {
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

  let body: any = {};
  try {
    body = await request.json();
  } catch (err) {
    return new Response(JSON.stringify({ error: 'invalid_payload' }), {
      status: 400,
      headers: { 'Content-Type': 'application/json', 'Access-Control-Allow-Origin': '*' },
    });
  }

  const { s3_bucket, s3_key, s3_etag = null } = body;

  // Validation
  if (!s3_bucket || !s3_key) {
    return new Response(JSON.stringify({ error: 'invalid_payload' }), {
      status: 400,
      headers: { 'Content-Type': 'application/json', 'Access-Control-Allow-Origin': '*' },
    });
  }

  // Key must end with .zip
  if (!s3_key.toLowerCase().endsWith('.zip')) {
    return new Response(JSON.stringify({ error: 'invalid_payload' }), {
      status: 400,
      headers: { 'Content-Type': 'application/json', 'Access-Control-Allow-Origin': '*' },
    });
  }

  // Key must be under uploads/<LDiHKID>/
  const requiredPrefix = `uploads/${ldihkId}/`;
  if (!s3_key.startsWith(requiredPrefix)) {
    return new Response(JSON.stringify({ error: 'unauthorized_import' }), {
      status: 403,
      headers: { 'Content-Type': 'application/json', 'Access-Control-Allow-Origin': '*' },
    });
  }

  const statePath = path.join(os.tmpdir(), 'ldihk_state.json');
  let state: any = { datasets: {}, imports: {} };

  try {
    const data = await fs.readFile(statePath, 'utf-8');
    state = JSON.parse(data);
  } catch (err) {
    // If it doesn't exist, we fallback
  }

  if (!state.imports) state.imports = {};
  if (!state.datasets) state.datasets = {};

  const importId = crypto.randomUUID();
  const now = new Date().toISOString();

  // Create import record
  const newImport = {
    import_id: importId,
    ldihk_id: ldihkId,
    status: 'queued',
    s3_bucket,
    s3_key,
    s3_etag,
    records_seen: 0,
    records_imported: 0,
    warnings_count: 0,
    error_message: null,
    created_at: now,
    started_at: null,
    finished_at: null,
  };

  state.imports[importId] = newImport;

  // Set youtube status to PROCESSING
  state.datasets.youtube = {
    status: 'PROCESSING',
    current_import_id: importId,
  };

  try {
    await fs.writeFile(statePath, JSON.stringify(state, null, 2));
  } catch (writeErr) {
    console.error('Failed to write state file:', writeErr);
  }

  return new Response(
    JSON.stringify({
      import_id: importId,
      ldihk_id: ldihkId,
      status: 'queued',
    }),
    {
      status: 200,
      headers: {
        'Content-Type': 'application/json',
        'Access-Control-Allow-Origin': '*',
      },
    }
  );
};
