import React, { useState, useEffect } from 'react';
import { shareApi } from '../../api/client';
import { Share2, Copy, Check, X, Globe, Sparkles } from 'lucide-react';

export default function ShareModal({ sessionId, sessionTitle, onClose }) {
  const [shareUrl, setShareUrl] = useState('');
  const [loading, setLoading] = useState(true);
  const [copied, setCopied] = useState(false);
  const [error, setError] = useState('');

  useEffect(() => {
    if (!sessionId) return;
    setLoading(true);
    setError('');
    shareApi.createShareLink(sessionId)
      .then((data) => {
        const fullUrl = `${window.location.origin}/share/${data.token}`;
        setShareUrl(fullUrl);
      })
      .catch((err) => {
        setError('Failed to create share link: ' + (err.message || 'Unknown error'));
      })
      .finally(() => setLoading(false));
  }, [sessionId]);

  const handleCopy = () => {
    if (!shareUrl) return;
    navigator.clipboard.writeText(shareUrl);
    setCopied(true);
    setTimeout(() => setCopied(false), 2500);
  };

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-black/70 backdrop-blur-md animate-fade-in">
      <div className="relative w-full max-w-lg bg-gray-950/90 border border-white/10 rounded-3xl p-6 shadow-[0_0_50px_rgba(99,102,241,0.25)] text-white">
        
        {/* Close Button */}
        <button
          onClick={onClose}
          className="absolute top-5 right-5 p-2 rounded-full hover:bg-white/10 text-gray-400 hover:text-white transition-colors"
        >
          <X size={18} />
        </button>

        {/* Header */}
        <div className="flex items-center gap-3 mb-4">
          <div className="w-10 h-10 rounded-2xl bg-gradient-to-tr from-indigo-500 to-purple-600 flex items-center justify-center shadow-lg shadow-indigo-500/20">
            <Share2 size={20} className="text-white" />
          </div>
          <div>
            <h3 className="text-lg font-bold">Share Conversation</h3>
            <p className="text-xs text-gray-400">Create a public, read-only snapshot of this chat</p>
          </div>
        </div>

        {/* Content */}
        <div className="space-y-4 my-5">
          <div className="p-3.5 rounded-2xl bg-black/40 border border-white/5 flex items-center gap-3 text-sm text-gray-300">
            <Globe size={18} className="text-indigo-400 shrink-0" />
            <span className="truncate">
              Anyone with this link will be able to view this tutoring session snapshot.
            </span>
          </div>

          {loading ? (
            <div className="py-8 flex flex-col items-center justify-center gap-3 text-gray-400">
              <div className="w-6 h-6 border-2 border-indigo-400 border-t-transparent rounded-full animate-spin" />
              <span className="text-xs font-medium">Generating snapshot link...</span>
            </div>
          ) : error ? (
            <div className="p-3 rounded-xl bg-red-500/10 border border-red-500/30 text-red-300 text-xs">
              {error}
            </div>
          ) : (
            <div className="space-y-2">
              <label className="text-[11px] uppercase font-bold text-gray-400 tracking-wider">Share Link</label>
              <div className="flex gap-2">
                <input
                  type="text"
                  readOnly
                  value={shareUrl}
                  className="flex-1 bg-black/60 border border-white/10 rounded-xl px-3.5 py-2.5 text-xs text-indigo-300 font-mono focus:outline-none select-all"
                />
                <button
                  onClick={handleCopy}
                  className="px-4 py-2.5 rounded-xl bg-gradient-to-r from-indigo-600 to-purple-600 hover:from-indigo-500 hover:to-purple-500 text-white font-medium text-xs flex items-center gap-1.5 shadow-lg shadow-indigo-600/30 transition-all hover:scale-105 active:scale-95"
                >
                  {copied ? (
                    <>
                      <Check size={14} className="text-green-300" />
                      <span>Copied!</span>
                    </>
                  ) : (
                    <>
                      <Copy size={14} />
                      <span>Copy Link</span>
                    </>
                  )}
                </button>
              </div>
            </div>
          )}
        </div>

        {/* Footer */}
        <div className="flex justify-end pt-3 border-t border-white/5">
          <button
            onClick={onClose}
            className="px-4 py-2 rounded-xl text-xs font-semibold text-gray-300 hover:bg-white/10 transition-colors"
          >
            Done
          </button>
        </div>
      </div>
    </div>
  );
}
