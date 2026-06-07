import React, { useState, useRef, useEffect } from 'react';
import { UploadCloud, CheckCircle2, AlertTriangle, RefreshCw, Database, Lock, Shield, Copy } from 'lucide-react';

const IS_MOCK_MODE = import.meta.env.PUBLIC_MOCK_API === 'true';
const API_BASE = IS_MOCK_MODE ? '' : (import.meta.env.PUBLIC_API_URL || '');

interface UploadZoneProps {
  onUploadComplete: (s3Key: string, s3Bucket: string) => void;
  sessionToken: string | null;
  onSessionGenerated?: (newSessionToken: string) => void;
}

const ADJECTIVES = [
  'cosmic', 'quantum', 'aurora', 'cyber', 'neon', 'stellar', 'plasma', 'shadow',
  'solar', 'vortex', 'emerald', 'sapphire', 'obsidian', 'spectral', 'lunar',
  'hyper', 'alpha', 'omega', 'magnetic', 'crypto'
];
const NOUNS = [
  'pegasus', 'nebula', 'hawk', 'leopard', 'viper', 'phoenix', 'cyclone', 'glider',
  'pulsar', 'comet', 'horizon', 'phantom', 'beacon', 'titan', 'matrix', 'falcon',
  'griffin', 'sentinel', 'orion'
];
const VERBS = [
  'gliding', 'soaring', 'beaming', 'echoing', 'surging', 'orbiting', 'hunting',
  'pulsing', 'flaring', 'shining', 'blazing', 'drifting'
];

function generateCoolId(): string {
  const adj = ADJECTIVES[Math.floor(Math.random() * ADJECTIVES.length)];
  const noun = NOUNS[Math.floor(Math.random() * NOUNS.length)];
  const verb = VERBS[Math.floor(Math.random() * VERBS.length)];
  return `ldihk-${adj}-${noun}-${verb}`;
}

function parseS3BucketAndKey(url: string, headers: any): { bucket: string, key: string } {
  let key = headers?.['x-amz-s3-key'] || '';
  let bucket = '';

  try {
    const urlObj = new URL(url);
    const hostname = urlObj.hostname;
    const pathname = urlObj.pathname;

    if (hostname.includes('.s3')) {
      bucket = hostname.split('.s3')[0];
      if (!key) {
        key = decodeURIComponent(pathname.substring(1));
      }
    } else {
      const parts = pathname.substring(1).split('/');
      bucket = parts[0];
      if (!key) {
        key = decodeURIComponent(parts.slice(1).join('/'));
      }
    }
  } catch (e) {
    console.error("Failed to parse S3 URL:", e);
  }

  if (key.includes('?')) {
    key = key.split('?')[0];
  }

  return { bucket, key };
}

export default function UploadZone({ onUploadComplete, sessionToken, onSessionGenerated }: UploadZoneProps) {
  const [dragActive, setDragActive] = useState(false);
  const [status, setStatus] = useState<'IDLE' | 'UPLOADING' | 'SUCCESS' | 'ERROR'>('IDLE');
  const [progress, setProgress] = useState(0);
  const [errorMessage, setErrorMessage] = useState('');
  const [fileName, setFileName] = useState('');
  const [fileSize, setFileSize] = useState('');
  const [showWarningModal, setShowWarningModal] = useState(false);
  const [showIdPromptModal, setShowIdPromptModal] = useState(false);
  const [generatedId, setGeneratedId] = useState('');
  const [copiedId, setCopiedId] = useState(false);
  const [pendingFile, setPendingFile] = useState<File | null>(null);

  const uploadXhr = useRef<XMLHttpRequest | null>(null);
  const fileInputRef = useRef<HTMLInputElement>(null);
  const registerFormRef = useRef<HTMLFormElement>(null);
  const [generatedIdForForm, setGeneratedIdForForm] = useState('');
  const [isMock, setIsMock] = useState<boolean | null>(null);

  useEffect(() => {
    fetch('/api/uploader-info')
      .then((res) => {
        if (!res.ok) throw new Error();
        return res.json();
      })
      .then((data) => setIsMock(data.isMock))
      .catch((err) => {
        console.error('Failed to retrieve uploader info:', err);
        setIsMock(true);
      });
  }, []);

  const formatFileSize = (bytes: number) => {
    if (bytes === 0) return '0 Bytes';
    const k = 1024;
    const sizes = ['Bytes', 'KB', 'MB', 'GB'];
    const i = Math.floor(Math.log(bytes) / Math.log(k));
    return parseFloat((bytes / Math.pow(k, i)).toFixed(2)) + ' ' + sizes[i];
  };

  const handleDrag = (e: React.DragEvent) => {
    e.preventDefault();
    e.stopPropagation();
    if (e.type === 'dragenter' || e.type === 'dragover') {
      setDragActive(true);
    } else if (e.type === 'dragleave') {
      setDragActive(false);
    }
  };

  const handleDrop = (e: React.DragEvent) => {
    e.preventDefault();
    e.stopPropagation();
    setDragActive(false);

    if (e.dataTransfer.files && e.dataTransfer.files[0]) {
      const file = e.dataTransfer.files[0];
      if (!file.name.toLowerCase().endsWith('.zip')) {
        setStatus('ERROR');
        setErrorMessage('Only ZIP files (.zip) are supported.');
        return;
      }
      setPendingFile(file);
      
      // If user is not logged in OR uploading a zip file, show privacy warning modal
      if (!sessionToken || file.name.toLowerCase().endsWith('.zip') || file.type === 'application/zip') {
        setShowWarningModal(true);
      } else {
        startUploadFlow(file, sessionToken);
      }
    }
  };

  const handleFileChange = (e: React.ChangeEvent<HTMLInputElement>) => {
    if (e.target.files && e.target.files[0]) {
      const file = e.target.files[0];
      if (!file.name.toLowerCase().endsWith('.zip')) {
        setStatus('ERROR');
        setErrorMessage('Only ZIP files (.zip) are supported.');
        return;
      }
      setPendingFile(file);
      
      if (!sessionToken || file.name.toLowerCase().endsWith('.zip') || file.type === 'application/zip') {
        setShowWarningModal(true);
      } else {
        startUploadFlow(file, sessionToken);
      }
    }
  };

  const handleConfirmWarning = () => {
    setShowWarningModal(false);
    
    if (!sessionToken) {
      // Generate ID and show the ID prompt modal to make them note it down
      const newId = generateCoolId();
      setGeneratedId(newId);
      setGeneratedIdForForm(newId);
      setShowIdPromptModal(true);
    } else {
      if (pendingFile) {
        startUploadFlow(pendingFile, sessionToken);
      }
      setPendingFile(null);
    }
  };

  const handleCancelWarning = () => {
    setShowWarningModal(false);
    setPendingFile(null);
    if (fileInputRef.current) {
      fileInputRef.current.value = '';
    }
  };

  const handleConfirmIdPrompt = () => {
    setShowIdPromptModal(false);
    
    // 1. Submit hidden form to prompt browser password manager
    if (registerFormRef.current) {
      const btn = registerFormRef.current.querySelector('button');
      if (btn) btn.click();
    }
    
    // 2. Set token in parent component state
    if (onSessionGenerated) {
      onSessionGenerated(generatedId);
    }
    
    // 3. Start file upload
    if (pendingFile) {
      startUploadFlow(pendingFile, generatedId);
    }
    setPendingFile(null);
  };

  const handleCancelIdPrompt = () => {
    setShowIdPromptModal(false);
    setGeneratedId('');
    setGeneratedIdForForm('');
    setPendingFile(null);
    if (fileInputRef.current) {
      fileInputRef.current.value = '';
    }
  };

  const copyIdToClipboard = () => {
    if (generatedId) {
      navigator.clipboard.writeText(generatedId);
      setCopiedId(true);
      setTimeout(() => setCopiedId(false), 2000);
    }
  };

  const startUploadFlow = async (file: File, activeToken: string) => {
    setStatus('UPLOADING');
    setProgress(0);
    setErrorMessage('');
    setFileName(file.name);
    setFileSize(formatFileSize(file.size));

    try {
      // 1. Fetch pre-signed S3 upload url (mocked locally via authenticated POST)
      const response = await fetch('/api/upload-url', {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          'Authorization': `Bearer ${activeToken}`
        },
        body: JSON.stringify({
          filename: file.name,
          contentType: file.type || 'application/zip',
        })
      });
      
      if (!response.ok) {
        throw new Error('Failed to retrieve upload configuration credentials.');
      }
      
      const { url, method, headers, isMock: respIsMock } = await response.json();
      if (respIsMock !== undefined) {
        setIsMock(respIsMock);
      }

      // 2. Perform direct binary PUT upload bypassing local web server
      const xhr = new XMLHttpRequest();
      uploadXhr.current = xhr;
      
      xhr.open(method, url, true);

      // Set headers returned by the presigned URL generator
      if (headers) {
        Object.entries(headers).forEach(([key, value]) => {
          xhr.setRequestHeader(key, value as string);
        });
      }

      // Track progress
      xhr.upload.onprogress = (event) => {
        if (event.lengthComputable) {
          const percentage = Math.round((event.loaded / event.total) * 100);
          setProgress(percentage);
        }
      };

      // Handle response
      xhr.onload = () => {
        if (xhr.status >= 200 && xhr.status < 300) {
          setStatus('SUCCESS');
          setProgress(100);
          const { bucket, key } = parseS3BucketAndKey(url, headers);
          const finalBucket = bucket || 'ldihk-ingress-bucket';
          const finalKey = key || headers?.['x-amz-s3-key'] || `uploads/${activeToken}/${file.name}`;
          onUploadComplete(finalKey, finalBucket);
        } else {
          setStatus('ERROR');
          setErrorMessage(`Server responded with status code: ${xhr.status}`);
        }
      };

      // Handle network errors
      xhr.onerror = () => {
        setStatus('ERROR');
        setErrorMessage('Network connection lost during upload stream.');
      };

      // Set timeout boundaries (e.g. 5 minutes for massive files)
      xhr.timeout = 300000;
      xhr.ontimeout = () => {
        setStatus('ERROR');
        setErrorMessage('Upload request timed out (5-minute threshold exceeded).');
      };

      xhr.send(file);
    } catch (err: any) {
      console.error(err);
      setStatus('ERROR');
      setErrorMessage(err.message || 'An unexpected error occurred during uploader initiation.');
    }
  };

  const cancelUpload = () => {
    if (uploadXhr.current) {
      uploadXhr.current.abort();
      setStatus('IDLE');
      setProgress(0);
    }
  };

  return (
    <div className="w-full max-w-2xl mx-auto">
      <div
        className={`relative rounded-3xl p-8 border-2 border-dashed transition-all duration-200 ${
          dragActive
            ? 'border-brand-teal bg-brand-teal/5'
            : status === 'UPLOADING'
            ? 'border-brand-navy/20 bg-brand-beige/20'
            : 'border-brand-navy/30 bg-brand-beige/40 hover:bg-brand-beige/60'
        }`}
        onDragEnter={handleDrag}
        onDragLeave={handleDrag}
        onDragOver={handleDrag}
        onDrop={handleDrop}
      >
        {isMock !== null && (
          <div className="absolute top-4 right-4 z-10">
            <span className={`inline-flex items-center gap-1.5 text-[9px] font-black uppercase tracking-wider px-2.5 py-1 rounded-full border shadow-sm ${
              isMock 
                ? 'bg-amber-50/80 text-amber-800 border-amber-200' 
                : 'bg-emerald-50/80 text-emerald-800 border-emerald-200'
            }`}>
              <span className={`w-1.5 h-1.5 rounded-full ${
                isMock ? 'bg-amber-500 animate-pulse' : 'bg-emerald-500 animate-pulse'
              }`}></span>
              {isMock ? 'Mock Ingestion' : 'AWS S3 Live Ingestion'}
            </span>
          </div>
        )}
        {status === 'IDLE' && (
          <div className="flex flex-col items-center justify-center py-8 text-center">
            <div className="w-14 h-14 rounded-2xl bg-white border border-brand-navy/10 flex items-center justify-center text-brand-teal mb-4 shadow-sm">
              <UploadCloud className="w-7 h-7" />
            </div>
            <p className="font-bold text-brand-navy text-base mb-1">
              Drag & Drop your platform archive here
            </p>
            <p className="text-xs text-brand-navy/60 mb-6">
              Supports standard dataset ZIP files containing event metrics
            </p>
            <label className="px-5 py-2.5 rounded-xl bg-brand-teal text-white font-bold text-sm cursor-pointer hover:bg-brand-teal/95 shadow-md shadow-brand-teal/15 transition-all hover:-translate-y-0.5 duration-150">
              Browse Files
              <input
                ref={fileInputRef}
                type="file"
                className="hidden"
                accept=".zip"
                onChange={handleFileChange}
              />
            </label>
          </div>
        )}

        {status === 'UPLOADING' && (
          <div className="space-y-6 py-4">
            <div className="flex items-center justify-between">
              <div className="flex items-center gap-3">
                <div className="w-10 h-10 rounded-xl bg-brand-teal/10 flex items-center justify-center text-brand-teal">
                  <RefreshCw className="w-5 h-5 animate-spin" />
                </div>
                <div className="text-left">
                  <span className="font-bold text-brand-navy text-sm block truncate max-w-xs">{fileName}</span>
                  <span className="text-xs text-brand-navy/60 block">{fileSize}</span>
                </div>
              </div>
              <button
                onClick={cancelUpload}
                className="text-xs font-semibold text-brand-peach hover:text-brand-peach/85 transition-colors border border-brand-peach/30 px-3 py-1.5 rounded-lg bg-white"
              >
                Abort Upload
              </button>
            </div>

            {/* Progress Bar Container */}
            <div className="space-y-2">
              <div className="flex justify-between items-center text-xs font-bold text-brand-navy">
                <span>Direct Binary Upload (Bypassing Ingress)</span>
                <span>{progress}%</span>
              </div>
              <div className="w-full bg-brand-navy/10 rounded-full h-3 overflow-hidden">
                <div
                  className="bg-brand-teal h-full rounded-full transition-all duration-150"
                  style={{ width: `${progress}%` }}
                ></div>
              </div>
            </div>
          </div>
        )}

        {status === 'SUCCESS' && (
          <div className="flex flex-col items-center justify-center py-6 text-center space-y-4">
            <div className="w-14 h-14 rounded-full bg-brand-teal/10 flex items-center justify-center text-brand-teal shadow-inner">
              <CheckCircle2 className="w-8 h-8" />
            </div>
            <div>
              <p className="font-bold text-brand-navy text-base">Ingestion Completed Successfully</p>
              <p className="text-xs text-brand-navy/60 mt-1">
                File: {fileName} ({fileSize})
              </p>
            </div>
            <button
              onClick={() => setStatus('IDLE')}
              className="text-xs font-bold text-brand-teal hover:underline"
            >
              Upload another file
            </button>
          </div>
        )}

        {status === 'ERROR' && (
          <div className="flex flex-col items-center justify-center py-6 text-center space-y-4">
            <div className="w-14 h-14 rounded-full bg-brand-peach/10 flex items-center justify-center text-brand-peach">
              <AlertTriangle className="w-8 h-8" />
            </div>
            <div>
              <p className="font-bold text-brand-navy text-base">Pipeline Ingestion Failed</p>
              <p className="text-xs text-brand-peach mt-1 max-w-md font-semibold">
                {errorMessage}
              </p>
            </div>
            <div className="flex items-center gap-3">
              <button
                onClick={() => setStatus('IDLE')}
                className="px-4 py-2 rounded-xl bg-brand-navy text-white font-bold text-xs hover:bg-brand-navy/90"
              >
                Reset Dropzone
              </button>
            </div>
          </div>
        )}
      </div>

      {/* Privacy & Consent Warning Modal */}
      {showWarningModal && pendingFile && (
        <div className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-brand-navy/40 backdrop-blur-sm animate-fade-in">
          <div className="bg-white border border-brand-navy/10 rounded-3xl p-6 sm:p-8 max-w-lg w-full shadow-2xl space-y-6 relative overflow-hidden animate-scale-up text-left">
            {/* Visual top accent bar */}
            <div className="absolute top-0 left-0 right-0 h-1.5 bg-gradient-to-r from-brand-teal via-brand-peach to-brand-teal"></div>
            
            {/* Modal Title */}
            <div className="flex items-start gap-4">
              <div className="w-12 h-12 rounded-2xl bg-brand-peach/15 flex items-center justify-center text-brand-peach shrink-0 border border-brand-peach/25">
                <AlertTriangle className="w-6 h-6" />
              </div>
              <div className="space-y-1">
                <h3 className="font-extrabold text-brand-navy text-lg tracking-tight">Privacy & Consent Agreement</h3>
                <p className="text-xs text-brand-navy/50 leading-normal">
                  Please review what data is extracted before authorizing the upload of <span className="font-semibold text-brand-navy">{pendingFile.name}</span>.
                </p>
              </div>
            </div>

            {/* Warning details and content parameters */}
            <div className="space-y-3 pt-2">
              <div className="flex gap-3 p-3.5 rounded-2xl bg-brand-beige/30 border border-brand-navy/5">
                <Database className="w-5 h-5 text-brand-teal shrink-0 mt-0.5" />
                <div className="text-xs text-brand-navy/80 leading-relaxed">
                  <strong className="block text-brand-navy font-bold mb-0.5">What is Extracted:</strong>
                  We only parse limited usage and content indicators (specifically <span className="font-semibold text-brand-teal">time, duration, content type, and tags</span>) to render your timelines.
                </div>
              </div>

              <div className="flex gap-3 p-3.5 rounded-2xl bg-brand-peach/5 border border-brand-peach/10">
                <Shield className="w-5 h-5 text-brand-peach shrink-0 mt-0.5" />
                <div className="text-xs text-brand-navy/80 leading-relaxed">
                  <strong className="block text-brand-peach font-bold mb-0.5">What is Excluded:</strong>
                  We <span className="font-bold text-brand-peach">do NOT extract</span> any private records, conversations, direct messages (DMs), photos, or contacts.
                </div>
              </div>

              <div className="flex gap-3 p-3.5 rounded-2xl bg-brand-teal/5 border border-brand-teal/10">
                <Lock className="w-5 h-5 text-brand-teal shrink-0 mt-0.5" />
                <div className="text-xs text-brand-navy/80 leading-relaxed">
                  <strong className="block text-brand-teal font-bold mb-0.5">Anonymous Storage:</strong>
                  No personal names, user handles, or account markers are stored. All database records are fully <span className="font-semibold text-brand-teal">anonymous</span>.
                </div>
              </div>
            </div>

            {/* Call to Actions */}
            <div className="flex flex-col sm:flex-row gap-3 pt-4 border-t border-brand-navy/5">
              <button
                onClick={handleCancelWarning}
                className="w-full sm:w-1/2 px-5 py-3 rounded-xl border border-brand-navy/15 text-brand-navy/70 hover:text-brand-navy hover:bg-brand-beige/20 text-xs font-bold transition-all duration-150 cursor-pointer text-center"
              >
                Cancel
              </button>
              <button
                onClick={handleConfirmWarning}
                className="w-full sm:w-1/2 px-5 py-3 rounded-xl bg-brand-teal hover:bg-brand-teal/95 text-white text-xs font-bold shadow-md shadow-brand-teal/15 hover:shadow-lg transition-all duration-150 cursor-pointer text-center"
              >
                Agree & Upload
              </button>
            </div>
          </div>
        </div>
      )}

      {/* LDiHK-ID Display & Prompt Modal */}
      {showIdPromptModal && (
        <div className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-brand-navy/40 backdrop-blur-sm animate-fade-in">
          <div className="bg-white border border-brand-navy/10 rounded-3xl p-6 sm:p-8 max-w-lg w-full shadow-2xl space-y-6 relative overflow-hidden animate-scale-up text-left">
            {/* Visual top accent bar */}
            <div className="absolute top-0 left-0 right-0 h-1.5 bg-gradient-to-r from-brand-teal via-brand-peach to-brand-teal"></div>
            
            {/* Modal Title */}
            <div className="flex items-start gap-4">
              <div className="w-12 h-12 rounded-2xl bg-brand-teal/15 flex items-center justify-center text-brand-teal shrink-0 border border-brand-teal/25">
                <Lock className="w-6 h-6" />
              </div>
              <div className="space-y-1">
                <h3 className="font-extrabold text-brand-navy text-lg tracking-tight">Your LDiHK-ID is Ready</h3>
                <p className="text-xs text-brand-navy/50 leading-normal">
                  A unique, secure credentials token has been generated for your anonymous session.
                </p>
              </div>
            </div>

            {/* Display Token */}
            <div className="space-y-2">
              <span className="text-[10px] uppercase tracking-wider font-extrabold text-brand-navy/60 block">
                Your Unique Console Key
              </span>
              <div className="font-mono text-sm sm:text-base font-black bg-brand-beige/50 p-4 rounded-2xl border border-brand-navy/10 text-brand-navy tracking-tight flex items-center justify-between gap-3 shadow-inner">
                <span className="truncate select-all">{generatedId}</span>
                <button
                  onClick={copyIdToClipboard}
                  className="px-3.5 py-2 rounded-xl bg-white border border-brand-navy/10 hover:border-brand-navy/20 font-bold text-xs flex items-center gap-1.5 transition-all cursor-pointer shadow-sm shrink-0"
                >
                  {copiedId ? (
                    <>
                      <CheckCircle2 className="w-3.5 h-3.5 text-brand-teal animate-pulse" />
                      Copied!
                    </>
                  ) : (
                    <>
                      <Copy className="w-3.5 h-3.5 text-brand-navy/60" />
                      Copy Key
                    </>
                  )}
                </button>
              </div>
            </div>

            {/* Alert box warning user to write it down */}
            <div className="flex gap-3 p-4 rounded-2xl bg-brand-peach/10 border border-brand-peach/30 text-brand-navy shadow-sm">
              <AlertTriangle className="w-5 h-5 text-brand-peach shrink-0 mt-0.5" />
              <div className="text-xs leading-relaxed">
                <strong className="block text-brand-peach font-bold mb-1">
                  Write this ID down or copy it to a safe place!
                </strong>
                LDiHK datasets are fully <span className="font-bold">anonymous</span>. We do not store your name or email, meaning <span className="font-bold text-brand-peach">we CANNOT recover this ID</span> if you lose it. If you close the window or clear cookies without noting it down, you will lose access to this console forever.
              </div>
            </div>

            {/* Modal Actions */}
            <div className="flex flex-col sm:flex-row gap-3 pt-4 border-t border-brand-navy/5">
              <button
                onClick={handleCancelIdPrompt}
                className="w-full sm:w-1/3 px-5 py-3 rounded-xl border border-brand-navy/15 text-brand-navy/70 hover:text-brand-navy hover:bg-brand-beige/20 text-xs font-bold transition-all duration-150 cursor-pointer text-center"
              >
                Cancel
              </button>
              <button
                onClick={handleConfirmIdPrompt}
                className="w-full sm:w-2/3 px-5 py-3 rounded-xl bg-brand-teal hover:bg-brand-teal/95 text-white text-xs font-bold shadow-md shadow-brand-teal/15 hover:shadow-lg transition-all duration-150 cursor-pointer text-center"
              >
                I've Saved It, Start Ingestion
              </button>
            </div>
          </div>
        </div>
      )}
      {/* Hidden registration form to trigger browser credential saving */}
      <form 
        ref={registerFormRef} 
        style={{ display: 'none' }} 
        onSubmit={(e) => e.preventDefault()}
      >
        <input 
          type="text" 
          name="username" 
          value="LDiHK User" 
          readOnly 
          autoComplete="username" 
        />
        <input 
          type="password" 
          name="password" 
          value={generatedIdForForm} 
          readOnly 
          autoComplete="new-password" 
        />
        <button type="submit">Register</button>
      </form>
    </div>
  );
}
