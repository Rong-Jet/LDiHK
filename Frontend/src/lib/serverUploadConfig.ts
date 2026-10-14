import type { S3UploadConfig } from './s3Presign';

/**
 * Server-only helper shared by the Astro upload routes so `/api/upload-url` and
 * `/api/uploader-info` always agree on whether live uploads are configured.
 *
 * Runtime `process.env` wins (Netlify injects site env vars into functions at
 * runtime); `import.meta.env` is the build-time / `astro dev` fallback.
 */
function pick(runtimeValue: string | undefined, buildValue: unknown): string | null {
  const candidate = runtimeValue ?? (typeof buildValue === 'string' ? buildValue : undefined);
  const trimmed = candidate?.trim();
  return trimmed ? trimmed : null;
}

export interface UploadTargetConfig {
  /** True when every value needed to presign a live upload is present. */
  configured: boolean;
  /** `s3` for AWS, `s3-compatible` when S3_ENDPOINT_URL is set (e.g. Cloudflare R2). */
  provider: 's3' | 's3-compatible' | null;
  config: S3UploadConfig | null;
}

export function readUploadTargetConfig(): UploadTargetConfig {
  const accessKeyId = pick(process.env.CUSTOM_AWS_ACCESS_KEY_ID, import.meta.env.CUSTOM_AWS_ACCESS_KEY_ID);
  const secretAccessKey = pick(process.env.CUSTOM_AWS_SECRET_ACCESS_KEY, import.meta.env.CUSTOM_AWS_SECRET_ACCESS_KEY);
  const region = pick(process.env.CUSTOM_AWS_REGION, import.meta.env.CUSTOM_AWS_REGION);
  const bucket = pick(process.env.S3_BUCKET, import.meta.env.S3_BUCKET);
  const endpoint = pick(process.env.S3_ENDPOINT_URL, import.meta.env.S3_ENDPOINT_URL);

  // AWS needs an explicit region; S3-compatible endpoints (R2) default to `auto`.
  const configured = !!(accessKeyId && secretAccessKey && bucket && (region || endpoint));
  if (!configured || !accessKeyId || !secretAccessKey || !bucket) {
    return { configured: false, provider: null, config: null };
  }

  return {
    configured: true,
    provider: endpoint ? 's3-compatible' : 's3',
    config: { accessKeyId, secretAccessKey, bucket, region, endpoint },
  };
}
