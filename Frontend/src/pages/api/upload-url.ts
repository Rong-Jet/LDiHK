import type { APIRoute } from 'astro';
import fs from 'fs/promises';
import path from 'path';
import os from 'os';

export const prerender = false;

export const INITIAL_STATE = {
  datasets: {
    youtube: { status: 'READY', min_date: '2026-05-08', max_date: '2026-06-06' },
  },
  imports: {},
  lastUploadPlatform: null,
  startedAt: 0
};

// Handle OPTIONS preflight requests for CORS compatibility
export const OPTIONS: APIRoute = async () => {
  return new Response(null, {
    status: 204,
    headers: {
      'Access-Control-Allow-Origin': '*',
      'Access-Control-Allow-Methods': 'GET, POST, OPTIONS',
      'Access-Control-Allow-Headers': 'Content-Type, Authorization',
      'Access-Control-Max-Age': '86400',
    },
  });
};

export const GET: APIRoute = async () => {
  // Reset state to initial mock state (YouTube & Instagram ready)
  const statePath = path.join(os.tmpdir(), 'ldihk_state.json');
  try {
    await fs.writeFile(statePath, JSON.stringify(INITIAL_STATE, null, 2));
  } catch (err) {
    console.error('Failed to reset state file:', err);
  }

  return new Response(
    JSON.stringify({ success: true, message: 'Pipeline status reset successfully.' }),
    {
      status: 200,
      headers: {
        'Content-Type': 'application/json',
        'Access-Control-Allow-Origin': '*',
      },
    }
  );
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
  } catch (e) {
    // Fallback if empty payload
  }

  const filename = body.filename || 'data.zip';
  const contentType = body.contentType || 'application/zip';
  const urlObj = new URL(request.url);

  const s3Key = `uploads/${ldihkId}/${filename}`;

  // Return S3 pre-signed upload credentials under v5 spec mapping
  return new Response(
    JSON.stringify({
      url: `${urlObj.origin}/api/mock-s3-upload`,
      method: 'PUT',
      headers: {
        'Content-Type': contentType,
        'x-amz-meta-filename': filename,
        'x-amz-meta-ldihkid': ldihkId,
        'x-amz-s3-key': s3Key
      },
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
