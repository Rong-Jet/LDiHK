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
      'Access-Control-Allow-Methods': 'PUT, OPTIONS',
      'Access-Control-Allow-Headers': 'Content-Type, x-amz-meta-filename',
      'Access-Control-Max-Age': '86400',
    },
  });
};

export const PUT: APIRoute = async ({ request }) => {
  try {
    const filename = request.headers.get('x-amz-meta-filename') || '';
    
    // Parse platform from filename metadata
    let platform = 'tiktok';
    const fnLower = filename.toLowerCase();
    if (fnLower.includes('youtube')) platform = 'youtube';
    else if (fnLower.includes('instagram')) platform = 'instagram';
    else if (fnLower.includes('tiktok')) platform = 'tiktok';
    else if (fnLower.includes('twitter') || fnLower.includes('x_data')) platform = 'twitter';
    else if (fnLower.includes('linkedin')) platform = 'linkedin';

    // Consume request stream to simulate upload progress completion
    const body = request.body;
    if (body) {
      const reader = body.getReader();
      let totalBytes = 0;
      while (true) {
        const { done, value } = await reader.read();
        if (done) break;
        if (value) totalBytes += value.length;
      }
      console.log(`Uploaded ${totalBytes} bytes for platform [${platform}] to S3.`);
    }

    // Mock S3 upload successfully consumed request body stream.
    // The import process will be triggered by the frontend calling POST /api/imports.

    return new Response(JSON.stringify({ success: true, platform }), {
      status: 200,
      headers: {
        'Content-Type': 'application/json',
        'Access-Control-Allow-Origin': '*',
      },
    });
  } catch (err: any) {
    console.error('Error during S3 mock upload:', err);
    return new Response(JSON.stringify({ error: err.message || 'Upload failed' }), {
      status: 500,
      headers: {
        'Content-Type': 'application/json',
        'Access-Control-Allow-Origin': '*',
      },
    });
  }
};
