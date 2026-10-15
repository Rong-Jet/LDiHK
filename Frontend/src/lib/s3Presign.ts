import { PutObjectCommand, S3Client } from '@aws-sdk/client-s3';
import { getSignedUrl } from '@aws-sdk/s3-request-presigner';

/**
 * Upload target configuration for AWS S3 or an S3-compatible store such as
 * Cloudflare R2. Kept free of Astro imports so it can be exercised from plain
 * Node scripts.
 */
export interface S3UploadConfig {
  accessKeyId: string;
  secretAccessKey: string;
  bucket: string;
  /** AWS region. Optional for S3-compatible endpoints (defaults to `auto`). */
  region?: string | null;
  /** S3-compatible endpoint, e.g. `https://<account-id>.r2.cloudflarestorage.com`. */
  endpoint?: string | null;
}

export const PRESIGNED_UPLOAD_TTL_SECONDS = 900;

export function createUploadS3Client(config: S3UploadConfig): S3Client {
  const endpoint = config.endpoint?.trim() || undefined;
  const region = config.region?.trim() || (endpoint ? 'auto' : undefined);

  return new S3Client({
    region,
    ...(endpoint ? { endpoint, forcePathStyle: true } : {}),
    credentials: {
      accessKeyId: config.accessKeyId,
      secretAccessKey: config.secretAccessKey,
    },
    // Since @aws-sdk/client-s3 3.729 the SDK adds flexible checksums by default.
    // For presigned PUT URLs that bakes `x-amz-checksum-crc32=AAAAAA==` (the CRC
    // of an empty body) into the query string, so every real browser upload is
    // rejected. Only send checksums when an operation strictly requires them.
    requestChecksumCalculation: 'WHEN_REQUIRED',
    responseChecksumValidation: 'WHEN_REQUIRED',
  });
}

/**
 * Presigned PUT for one ZIP. `contentLength` becomes a signed header, so the
 * storage rejects any upload whose size differs from the declared one: a
 * signed URL cannot be reused to push an arbitrarily large file.
 */
export async function presignZipUpload(
  config: S3UploadConfig,
  key: string,
  contentType: string,
  contentLength: number,
  expiresIn: number = PRESIGNED_UPLOAD_TTL_SECONDS
): Promise<string> {
  const client = createUploadS3Client(config);
  const command = new PutObjectCommand({
    Bucket: config.bucket,
    Key: key,
    ContentType: contentType,
    ContentLength: contentLength,
  });
  return getSignedUrl(client, command, { expiresIn });
}
