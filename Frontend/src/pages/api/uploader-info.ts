import type { APIRoute } from 'astro';
import { usesLocalMockApi } from '../../lib/env';

export const prerender = false;

// Handle OPTIONS preflight requests for CORS compatibility
export const OPTIONS: APIRoute = async () => {
  return new Response(null, {
    status: 204,
    headers: {
      'Access-Control-Allow-Origin': '*',
      'Access-Control-Allow-Methods': 'GET, OPTIONS',
      'Access-Control-Allow-Headers': 'Content-Type',
      'Access-Control-Max-Age': '86400',
    },
  });
};

// Tells the upload UI whether uploads go to real storage or the mock route.
// Live uploads are signed by the backend (POST /api/uploads), so this site
// holds no storage credentials; mock mode uses the local mock routes.
export const GET: APIRoute = async () => {
  return new Response(
    JSON.stringify({
      isMock: usesLocalMockApi,
      uploadConfigured: true,
      provider: usesLocalMockApi ? 'mock' : 'backend',
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
