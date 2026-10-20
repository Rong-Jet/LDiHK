import type { APIRoute } from 'astro';
import fs from 'fs/promises';
import path from 'path';
import os from 'os';
import { usesLocalMockApi } from '../../lib/env';
import { isValidLdihkId } from '../../lib/ldihkId';
import {
  SIGNING_LIMIT_PER_ID,
  SIGNING_LIMIT_PER_IP,
  hitRateLimit,
  maxUploadBytes,
  parseUploadSize,
} from '../../lib/uploadLimits';

export const prerender = false;

export const INITIAL_STATE = {
  datasets: {
    youtube: { status: 'READY', min_date: '2026-05-08', max_date: '2026-06-06' },
  },
  imports: {},
  lastUploadPlatform: null,
  startedAt: 0
};

const JSON_HEADERS = {
  'Content-Type': 'application/json',
  'Access-Control-Allow-Origin': '*',
};

function json(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), { status, headers: JSON_HEADERS });
}

/**
 * Upload object key: `uploads/<LDiHK-ID>/<name>.zip`. Path separators and
 * control characters are replaced, and the extension is lowercased because
 * the backend only queues keys ending in `.zip`.
 */
export function uploadKeyFor(ldihkId: string, rawFilename: unknown): string | null {
  const name = (typeof rawFilename === 'string' ? rawFilename : 'data.zip')
    .replace(/[\/\\\x00-\x1F]+/g, '_')
    .trim();
  if (!/\.zip$/i.test(name)) return null;
  const stem = name.slice(0, -4).replace(/^\.+/, '') || 'data';
  return `uploads/${ldihkId}/${stem}.zip`;
}

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

// Resets the simulated pipeline. Mock mode only: in live mode there is no
// local state to reset, and an unauthenticated GET must not change anything.
export const GET: APIRoute = async () => {
  if (!usesLocalMockApi) {
    return json({ error: 'not_found' }, 404);
  }
  const statePath = path.join(os.tmpdir(), 'ldihk_state.json');
  try {
    await fs.writeFile(statePath, JSON.stringify(INITIAL_STATE, null, 2));
  } catch (err) {
    console.error('Failed to reset state file:', err);
  }
  return json({ success: true, message: 'Pipeline status reset successfully.' });
};

export const POST: APIRoute = async ({ request, clientAddress }) => {
  // Live uploads are signed by the backend (POST /api/uploads), which enforces
  // the storage budget; this route only serves the mock upload flow.
  if (!usesLocalMockApi) {
    return json({ error: 'upload_moved', message: 'Uploads are signed by the backend (POST /api/uploads).' }, 410);
  }

  const authHeader = request.headers.get('Authorization') || '';
  if (!authHeader.startsWith('Bearer ')) {
    return json({ error: 'missing_authorization' }, 401);
  }

  const ldihkId = authHeader.slice('Bearer '.length).trim();
  if (!isValidLdihkId(ldihkId)) {
    return json({ error: 'invalid_authorization' }, 401);
  }

  let body: any = {};
  try {
    body = await request.json();
  } catch {
    // Empty payload: fall back to the default file name.
  }

  const s3Key = uploadKeyFor(ldihkId, body.filename);
  if (!s3Key) {
    return json({ error: 'invalid_filename', message: 'Only .zip archives can be uploaded.' }, 400);
  }

  const parsedSize = parseUploadSize(body.size);
  if ('error' in parsedSize) {
    const limitMb = Math.round(maxUploadBytes() / (1024 * 1024));
    return parsedSize.error === 'file_too_large'
      ? json({ error: 'file_too_large', message: `The archive is larger than ${limitMb} MB.` }, 413)
      : json({ error: 'invalid_size', message: 'The upload size is missing or invalid.' }, 400);
  }

  let ipAddress: string | null = null;
  try {
    ipAddress = clientAddress || null;
  } catch {
    // Some adapters cannot determine the client address.
  }
  const wait = hitRateLimit(`id:${ldihkId}`, SIGNING_LIMIT_PER_ID)
    ?? (ipAddress ? hitRateLimit(`ip:${ipAddress}`, SIGNING_LIMIT_PER_IP) : null);
  if (wait !== null) {
    return new Response(
      JSON.stringify({ error: 'rate_limited', message: `Too many uploads. Try again in ${Math.ceil(wait / 60)} min.` }),
      { status: 429, headers: { ...JSON_HEADERS, 'Retry-After': String(wait) } }
    );
  }
  const contentType = typeof body.contentType === 'string' && body.contentType ? body.contentType : 'application/zip';

  // Mock mode: upload to the local mock route instead of real storage.
  const filename = s3Key.split('/').pop() || 'data.zip';
  const urlObj = new URL(request.url);
  return json({
    url: `${urlObj.origin}/api/mock-s3-upload`,
    method: 'PUT',
    headers: {
      'Content-Type': contentType,
      'x-amz-meta-filename': filename,
      'x-amz-meta-ldihkid': ldihkId,
      'x-amz-s3-key': s3Key,
    },
    s3Bucket: 'local-mock-bucket',
    s3Key,
    isMock: true,
  });
};
