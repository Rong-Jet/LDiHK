import type { APIRoute } from 'astro';

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

export const GET: APIRoute = async () => {
  const backendApiBase = import.meta.env.PUBLIC_BACKEND_API_URL || import.meta.env.PUBLIC_API_URL || '';
  const hasAwsKeys = !!(
    (import.meta.env.AWS_ACCESS_KEY_ID || process.env.AWS_ACCESS_KEY_ID) && 
    (import.meta.env.AWS_SECRET_ACCESS_KEY || process.env.AWS_SECRET_ACCESS_KEY) && 
    (import.meta.env.AWS_REGION || process.env.AWS_REGION) && 
    (import.meta.env.S3_BUCKET || process.env.S3_BUCKET)
  );

  return new Response(
    JSON.stringify({
      isMock: !hasAwsKeys && !backendApiBase,
      uploadConfigured: hasAwsKeys || !backendApiBase,
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
