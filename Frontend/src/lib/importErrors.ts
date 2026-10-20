import type { GuidePlatform } from '../components/ExportGuide';

export interface ImportFailure {
  message: string;
  /** Export guide tab that explains how to fix it. */
  guide: GuidePlatform | null;
}

// The worker stores "<code>: <technical detail>"; known codes get a plain
// explanation that says what to change in the export.
const KNOWN_FAILURES: Record<string, ImportFailure> = {
  takeout_index_only: {
    message:
      "This ZIP only contains Google's table of contents (archive_browser.html), no YouTube data. Request a new Takeout with YouTube history selected, or upload the other ZIP part if Google sent several.",
    guide: 'youtube',
  },
  youtube_history_missing: {
    message:
      'This YouTube export has no watch history, so there is nothing to measure. In Google Takeout, keep "history" ticked under "All YouTube data included" and check that YouTube History is switched on in your Google account.',
    guide: 'youtube',
  },
  instagram_views_missing: {
    message:
      'This Instagram export has no viewed posts, Reels or stories. Export again with "Your Instagram activity" and "Ads information" selected.',
    guide: 'instagram',
  },
  no_supported_files: {
    message: 'This ZIP contains no YouTube, Instagram or TikTok history that LDiHK can read. Upload the export ZIP unchanged, as the platform sent it.',
    guide: 'youtube',
  },
  file_too_large: {
    message: 'A file in this export is too large. Export only your history (no videos) and try again.',
    guide: 'youtube',
  },
};

export function describeImportFailure(errorMessage: string | null | undefined): ImportFailure {
  if (!errorMessage) return { message: 'The import failed without an error message.', guide: null };
  const code = errorMessage.split(':', 1)[0].trim();
  return KNOWN_FAILURES[code] ?? { message: errorMessage, guide: null };
}
