import React, { useState } from 'react';
import { ChevronDown, HelpCircle } from 'lucide-react';

export type GuidePlatform = 'youtube' | 'instagram' | 'tiktok';

const TABS: { id: GuidePlatform; label: string }[] = [
  { id: 'youtube', label: 'YouTube' },
  { id: 'instagram', label: 'Instagram' },
  { id: 'tiktok', label: 'TikTok' },
];

const STEPS: Record<GuidePlatform, { steps: React.ReactNode[]; note: React.ReactNode }> = {
  youtube: {
    steps: [
      <>Open <a href="https://takeout.google.com" target="_blank" rel="noopener" className="text-brand-teal underline">takeout.google.com</a>, click <b>Deselect all</b>, then tick only <b>YouTube and YouTube Music</b>.</>,
      <>Click <b>All YouTube data included</b> and make sure <b>history</b> is ticked. Untick <b>videos</b> — that keeps the file small.</>,
      <>Click <b>Multiple formats</b> and set <b>History</b> to <b>JSON</b> (HTML works too).</>,
      <>Click <b>Next step</b>, choose <b>Export once</b> and <b>.zip</b>, then <b>Create export</b>.</>,
      <>Google emails you when it is ready (minutes to a few hours). Download the ZIP and drop it here unchanged.</>,
    ],
    note: (
      <>
        Your watch history must be switched on in your Google account (<i>YouTube History</i> in My Activity), or the export
        will be nearly empty. If your channel uses a brand account, export from the account you actually watch with.
      </>
    ),
  },
  instagram: {
    steps: [
      <>In the Instagram app or website open <b>Settings → Accounts Center → Your information and permissions → Export your information</b>.</>,
      <>Tap <b>Create export</b>, pick your Instagram account and <b>Export to device</b>.</>,
      <>Under <b>Customize information</b> keep at least <b>Your Instagram activity</b> and <b>Ads information</b> — the second one holds the posts and Reels you viewed.</>,
      <>Set <b>Date range: All time</b>, <b>Format: JSON</b> and <b>Media quality: Low</b>, then <b>Start export</b>.</>,
      <>When Instagram notifies you (usually within a day), download the ZIP and drop it here unchanged.</>,
    ],
    note: (
      <>
        Instagram only exports the <b>last few days</b> of viewed posts and Reels (about a week; stories about a month).
        Your Instagram timeline will therefore be short — that is a limit of the export, not of your upload.
      </>
    ),
  },
  tiktok: {
    steps: [
      <>In TikTok open <b>Profile → Menu → Settings and privacy → Account → Download your data</b>.</>,
      <>Choose <b>All data</b> and the file format <b>JSON</b>, then <b>Request data</b>.</>,
      <>After a few hours download the file from the <b>Download data</b> tab and drop it here unchanged.</>,
    ],
    note: <>TikTok's <i>Watch History</i> only covers a recent period (often around six months), not your whole account history.</>,
  },
};

interface ExportGuideProps {
  /** Opens the guide on this platform, e.g. after a failed import. */
  focus?: GuidePlatform | null;
}

/** Short how-to for requesting the platform exports LDiHK can read. */
export default function ExportGuide({ focus = null }: ExportGuideProps) {
  const [open, setOpen] = useState(focus !== null);
  const [platform, setPlatform] = useState<GuidePlatform>(focus ?? 'youtube');
  const [lastFocus, setLastFocus] = useState(focus);
  if (focus !== lastFocus) {
    setLastFocus(focus);
    if (focus) {
      setOpen(true);
      setPlatform(focus);
    }
  }
  const { steps, note } = STEPS[platform];

  return (
    <div className="mt-4 rounded-2xl border border-brand-navy/10 bg-white text-left">
      <button
        type="button"
        onClick={() => setOpen(!open)}
        aria-expanded={open}
        className="w-full flex items-center justify-between gap-3 px-4 py-3 text-sm font-bold text-brand-navy cursor-pointer"
      >
        <span className="flex items-center gap-2">
          <HelpCircle className="w-4 h-4 text-brand-teal" />
          How do I get my export?
        </span>
        <ChevronDown className={`w-4 h-4 text-brand-navy/50 transition-transform ${open ? 'rotate-180' : ''}`} />
      </button>
      {open && (
        <div className="px-4 pb-4 space-y-3">
          <div className="flex gap-1.5" role="tablist">
            {TABS.map((tab) => (
              <button
                key={tab.id}
                type="button"
                role="tab"
                aria-selected={platform === tab.id}
                onClick={() => setPlatform(tab.id)}
                className={`px-3 py-1.5 rounded-lg text-xs font-bold cursor-pointer border ${
                  platform === tab.id
                    ? 'bg-brand-teal text-white border-brand-teal'
                    : 'bg-white text-brand-navy/70 border-brand-navy/15 hover:text-brand-navy'
                }`}
              >
                {tab.label}
              </button>
            ))}
          </div>
          <ol className="list-decimal pl-5 space-y-1.5 text-xs text-brand-navy/80 leading-relaxed">
            {steps.map((step, index) => <li key={index}>{step}</li>)}
          </ol>
          <p className="text-[11px] text-brand-navy/60 leading-relaxed bg-brand-beige/40 rounded-xl px-3 py-2">{note}</p>
        </div>
      )}
    </div>
  );
}
