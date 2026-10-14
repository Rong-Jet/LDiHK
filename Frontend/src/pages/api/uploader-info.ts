import type { APIRoute } from 'astro';
import { isMockApiMode, usesLocalMockApi } from '../../lib/env';
import { readUploadTargetConfig } from '../../lib/serverUploadConfig';

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
// Must agree with POST /api/upload-url, which reads the same configuration.
export const GET: APIRoute = async () => {
  const target = readUploadTargetConfig();
  const liveUploads = !isMockApiMode && target.configured;
  const mockUploads = !liveUploads && usesLocalMockApi;

  return new Response(
    JSON.stringify({
      isMock: mockUploads,
      uploadConfigured: liveUploads || mockUploads,
      provider: liveUploads ? target.provider : mockUploads ? 'mock' : null,
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
