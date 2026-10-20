import type { APIRoute } from 'astro';
import fs from 'fs/promises';
import path from 'path';
import os from 'os';
import { usesLocalMockApi } from '../../../lib/env';
import { isValidLdihkId } from '../../../lib/ldihkId';

export const prerender = false;

// Mock of the backend's POST /api/population/reference (mock mode only):
// fixed, clearly simulated reference values.
const JSON_HEADERS = { 'Content-Type': 'application/json', 'Access-Control-Allow-Origin': '*' };

function json(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), { status, headers: JSON_HEADERS });
}

export const OPTIONS: APIRoute = async () => new Response(null, {
  status: 204,
  headers: {
    'Access-Control-Allow-Origin': '*',
    'Access-Control-Allow-Methods': 'POST, OPTIONS',
    'Access-Control-Allow-Headers': 'Content-Type, Authorization',
  },
});

export const POST: APIRoute = async ({ request }) => {
  if (!usesLocalMockApi) return json({ error: 'backend_not_configured' }, 503);
  const authHeader = request.headers.get('Authorization') || '';
  const ldihkId = authHeader.startsWith('Bearer ') ? authHeader.slice('Bearer '.length).trim() : '';
  if (!isValidLdihkId(ldihkId)) return json({ error: 'invalid_authorization' }, 401);

  let profile = { age_range: null as string | null, sex: null as string | null };
  try {
    const state = JSON.parse(await fs.readFile(path.join(os.tmpdir(), 'ldihk_state.json'), 'utf-8'));
    profile = state.profiles?.[ldihkId] ?? profile;
  } catch {
    // No mock state yet.
  }
  const sex = profile.sex === 'female' || profile.sex === 'male' ? profile.sex : null;
  const cohort = profile.age_range || sex;
  return json({
    ready: true,
    profile,
    comparisonGroup: cohort
      ? { basis: 'cohort', ageRanges: profile.age_range ? [profile.age_range, profile.age_range] : null, sex, size: 60 }
      : { basis: 'everyone', ageRanges: null, sex: null, size: 1500 },
    cohort: { dailyHours: 0.9, lateNightHours: 0.2, fragmentation: 0.12 },
    overall: { dailyHours: 0.7, lateNightHours: 0.12, fragmentation: 0.1 },
  });
};
