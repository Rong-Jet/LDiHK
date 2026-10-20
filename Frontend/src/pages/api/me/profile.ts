import type { APIRoute } from 'astro';
import fs from 'fs/promises';
import path from 'path';
import os from 'os';
import { usesLocalMockApi } from '../../../lib/env';
import { isValidLdihkId } from '../../../lib/ldihkId';
import { AGE_RANGES, SEX_OPTIONS } from '../../../lib/profile';

export const prerender = false;

// Mock of the backend's PATCH /api/me/profile (mock mode only).
const STATE_PATH = path.join(os.tmpdir(), 'ldihk_state.json');
const JSON_HEADERS = { 'Content-Type': 'application/json', 'Access-Control-Allow-Origin': '*' };

function json(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), { status, headers: JSON_HEADERS });
}

export const OPTIONS: APIRoute = async () => new Response(null, {
  status: 204,
  headers: {
    'Access-Control-Allow-Origin': '*',
    'Access-Control-Allow-Methods': 'PATCH, OPTIONS',
    'Access-Control-Allow-Headers': 'Content-Type, Authorization',
  },
});

export const PATCH: APIRoute = async ({ request }) => {
  if (!usesLocalMockApi) return json({ error: 'backend_not_configured' }, 503);
  const authHeader = request.headers.get('Authorization') || '';
  const ldihkId = authHeader.startsWith('Bearer ') ? authHeader.slice('Bearer '.length).trim() : '';
  if (!isValidLdihkId(ldihkId)) return json({ error: 'invalid_authorization' }, 401);

  let body: any = null;
  try {
    body = await request.json();
  } catch {
    return json({ error: 'invalid_profile', fields: { body: 'must_be_json_object' } }, 400);
  }
  const errors: Record<string, string> = {};
  const sex = body?.sex === 'prefer_not_to_say' ? null : body?.sex;
  if (body?.age_range != null && !(AGE_RANGES as readonly string[]).includes(body.age_range)) errors.age_range = 'invalid_value';
  if (sex != null && !SEX_OPTIONS.some((option) => option.value === sex)) errors.sex = 'invalid_value';
  if (Object.keys(errors).length) return json({ error: 'invalid_profile', fields: errors }, 400);

  let state: any = {};
  try {
    state = JSON.parse(await fs.readFile(STATE_PATH, 'utf-8'));
  } catch {
    // No mock state yet.
  }
  const current = state.profiles?.[ldihkId] ?? { age_range: null, sex: null };
  const profile = {
    age_range: 'age_range' in (body ?? {}) ? body.age_range : current.age_range,
    sex: 'sex' in (body ?? {}) ? sex : current.sex,
  };
  state.profiles = { ...(state.profiles ?? {}), [ldihkId]: profile };
  await fs.writeFile(STATE_PATH, JSON.stringify(state, null, 2));
  return json({ profile });
};
