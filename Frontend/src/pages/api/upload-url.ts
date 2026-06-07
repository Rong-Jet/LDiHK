import type { APIRoute } from 'astro';
import fs from 'fs/promises';
import path from 'path';
import os from 'os';
import { S3Client, PutObjectCommand } from '@aws-sdk/client-s3';
import { getSignedUrl } from '@aws-sdk/s3-request-presigner';

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
  // Reset state to initial mock state (YouTube ready)
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

  // AWS Configuration lookup
  const isMockMode = import.meta.env.PUBLIC_MOCK_API === 'true';
  const awsAccessKeyId = import.meta.env.AWS_ACCESS_KEY_ID || process.env.AWS_ACCESS_KEY_ID || import.meta.env.CUSTOM_AWS_ACCESS_KEY_ID || process.env.CUSTOM_AWS_ACCESS_KEY_ID;
  const awsSecretAccessKey = import.meta.env.AWS_SECRET_ACCESS_KEY || process.env.AWS_SECRET_ACCESS_KEY || import.meta.env.CUSTOM_AWS_SECRET_ACCESS_KEY || process.env.CUSTOM_AWS_SECRET_ACCESS_KEY;
  const awsRegion = import.meta.env.AWS_REGION || process.env.AWS_REGION || import.meta.env.CUSTOM_AWS_REGION || process.env.CUSTOM_AWS_REGION;
  const s3Bucket = import.meta.env.S3_BUCKET || process.env.S3_BUCKET;

  const hasAwsKeys = !isMockMode && !!(awsAccessKeyId && awsSecretAccessKey && awsRegion && s3Bucket);

  if (hasAwsKeys) {
    try {
      const s3Client = new S3Client({
        region: awsRegion,
        credentials: {
          accessKeyId: awsAccessKeyId,
          secretAccessKey: awsSecretAccessKey,
        }
      });

      const command = new PutObjectCommand({
        Bucket: s3Bucket,
        Key: s3Key,
        ContentType: contentType,
      });

      // Generate a real AWS S3 pre-signed PUT URL valid for 15 minutes (900 seconds)
      const presignedUrl = await getSignedUrl(s3Client, command, { expiresIn: 900 });

      return new Response(
        JSON.stringify({
          url: presignedUrl,
          method: 'PUT',
          headers: {
            'Content-Type': contentType,
          },
          isMock: false
        }),
        {
          status: 200,
          headers: {
            'Content-Type': 'application/json',
            'Access-Control-Allow-Origin': '*',
          },
        }
      );
    } catch (err: any) {
      console.error('Failed to generate S3 pre-signed URL:', err);
      return new Response(
        JSON.stringify({ error: 's3_signature_failure', message: err.message }),
        {
          status: 500,
          headers: {
            'Content-Type': 'application/json',
            'Access-Control-Allow-Origin': '*',
          },
        }
      );
    }
  }

  // Fallback: Return S3 pre-signed upload credentials under mock uploader
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
      isMock: true
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
