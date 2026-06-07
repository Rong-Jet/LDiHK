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
  const isMockMode = import.meta.env.PUBLIC_MOCK_API === 'true';
  const awsAccessKeyId = import.meta.env.CUSTOM_AWS_ACCESS_KEY_ID || process.env.CUSTOM_AWS_ACCESS_KEY_ID;
  const awsSecretAccessKey = import.meta.env.CUSTOM_AWS_SECRET_ACCESS_KEY || process.env.CUSTOM_AWS_SECRET_ACCESS_KEY;
  const awsRegion = import.meta.env.CUSTOM_AWS_REGION || process.env.CUSTOM_AWS_REGION;
  const s3Bucket = import.meta.env.S3_BUCKET || process.env.S3_BUCKET;
  const hasAwsKeys = !!(awsAccessKeyId && awsSecretAccessKey && awsRegion && s3Bucket);

  return new Response(
    JSON.stringify({ isMock: isMockMode || !hasAwsKeys }),
    {
      status: 200,
      headers: {
        'Content-Type': 'application/json',
        'Access-Control-Allow-Origin': '*',
      },
    }
  );
};
