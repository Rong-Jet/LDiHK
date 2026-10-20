import { BlobReader, BlobWriter, ZipReader, ZipWriter, configure, type Entry, type FileEntry } from '@zip.js/zip.js';

// Keep all work on the main thread's async streams (native Compression/DecompressionStream);
// avoids shipping/allowing blob: web workers. Kept entries are copied raw anyway.
configure({ useWebWorkers: false });

/**
 * Browser-side ZIP trimming before upload.
 *
 * Platform exports (Google Takeout, TikTok, Instagram) are dominated by videos
 * and photos the backend never reads. It opens the archive through its
 * central directory (BlobReader reads byte ranges lazily, the file is never
 * loaded into memory as a whole) and re-zips only the non-media entries. Kept
 * entries are copied with `passThrough`, i.e. their compressed bytes are moved
 * as-is without decompressing or recompressing.
 */

/** Archives above this size are slimmed before upload. */
/** Keep in sync with the threshold in hooks/useUploadController.tsx. */
export const SLIM_THRESHOLD_BYTES = 20 * 1024 * 1024;

export const DROPPED_EXTENSIONS: ReadonlySet<string> = new Set([
  // video
  'mp4', 'mov', 'm4v', 'webm', 'mkv', 'avi', '3gp', '3g2', 'wmv', 'flv', 'mpg', 'mpeg', 'm2ts', 'mts', 'vob', 'ogv',
  // images
  'jpg', 'jpeg', 'png', 'gif', 'webp', 'heic', 'heif', 'bmp', 'tif', 'tiff', 'avif', 'jxl', 'ico', 'psd',
  'dng', 'cr2', 'nef', 'arw', 'raw',
  // audio
  'mp3', 'm4a', 'aac', 'wav', 'ogg', 'oga', 'opus', 'flac', 'amr', 'wma', 'aiff', 'aif', 'weba', 'mid', 'midi',
  // nested archives
  'zip', '7z', 'rar', 'gz', 'tgz', 'bz2', 'xz', 'tar',
]);

export function fileExtension(filename: string): string {
  const base = filename.split('/').pop() ?? filename;
  const dot = base.lastIndexOf('.');
  return dot > 0 ? base.slice(dot + 1).toLowerCase() : '';
}

export function isDroppedEntry(filename: string): boolean {
  return DROPPED_EXTENSIONS.has(fileExtension(filename));
}

export interface SlimResult {
  blob: Blob;
  originalBytes: number;
  slimmedBytes: number;
  keptEntries: number;
  removedEntries: number;
}

export interface SlimOptions {
  signal?: AbortSignal;
  /** Fraction in [0, 1] of kept (compressed) bytes copied so far. */
  onProgress?: (fraction: number) => void;
}

function throwIfAborted(signal?: AbortSignal) {
  if (signal?.aborted) throw new DOMException('Slimming aborted', 'AbortError');
}

function isFileEntry(entry: Entry): entry is FileEntry {
  return !entry.directory;
}

/**
 * Returns a slimmed copy of `archive`, or `null` when there is nothing to
 * remove (callers then upload the original). Throws on unreadable or
 * encrypted archives so callers can fall back to the original file.
 */
export async function slimZipArchive(archive: Blob, options: SlimOptions = {}): Promise<SlimResult | null> {
  const { signal, onProgress } = options;
  const reader = new ZipReader(new BlobReader(archive));
  try {
    const entries = await reader.getEntries();
    throwIfAborted(signal);

    const files = entries.filter(isFileEntry);
    if (files.some((entry) => entry.encrypted)) {
      throw new Error('Encrypted archives cannot be slimmed.');
    }
    const kept = files.filter((entry) => !isDroppedEntry(entry.filename));
    const removedEntries = files.length - kept.length;
    if (removedEntries === 0) return null;

    const totalBytes = kept.reduce((sum, entry) => sum + entry.compressedSize, 0) || 1;
    let copiedBytes = 0;
    onProgress?.(0);

    const writer = new ZipWriter(new BlobWriter('application/zip'));
    for (const entry of kept) {
      throwIfAborted(signal);
      if (entry.compressedSize <= entry.uncompressedSize) {
        // Copy the compressed bytes verbatim (no inflate/deflate round trip).
        const raw = await entry.getData(new BlobWriter(), { passThrough: true, signal });
        await writer.add(entry.filename, new BlobReader(raw), {
          passThrough: true,
          uncompressedSize: entry.uncompressedSize,
          signature: entry.signature,
          compressionMethod: entry.compressionMethod,
          lastModDate: entry.lastModDate,
          signal,
        });
      } else {
        // zip.js rejects passThrough reads whose compressed size exceeds the
        // uncompressed size (tiny files), so round-trip those few bytes instead.
        const data = await entry.getData(new BlobWriter(), { signal });
        await writer.add(entry.filename, new BlobReader(data), { lastModDate: entry.lastModDate, signal });
      }
      copiedBytes += entry.compressedSize;
      onProgress?.(Math.min(1, copiedBytes / totalBytes));
    }
    throwIfAborted(signal);
    const blob = await writer.close();

    return {
      blob,
      originalBytes: archive.size,
      slimmedBytes: blob.size,
      keptEntries: kept.length,
      removedEntries,
    };
  } finally {
    await reader.close().catch(() => undefined);
  }
}
