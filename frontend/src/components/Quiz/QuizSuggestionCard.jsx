import React, { useState } from 'react';
import { Zap, ChevronRight, X } from 'lucide-react';

/**
 * QuizSuggestionCard
 *
 * Inline card shown immediately after a tutor message when the AI detects
 * that a concept/topic explanation is complete. Prompts the student to
 * take a quick quiz on that topic.
 *
 * Props:
 *   topic      (string) — topic that was just explained
 *   subject    (string)
 *   numQuestions (number) — default 7
 *   onAccept   () => void — student clicks "Take Quiz"
 *   onSkip     () => void — student clicks "Skip"
 */
export default function QuizSuggestionCard({ topic, subject, numQuestions = 7, onAccept, onSkip }) {
  const [dismissed, setDismissed] = useState(false);

  if (dismissed) return null;

  const handleSkip = () => {
    setDismissed(true);
    if (onSkip) onSkip();
  };

  return (
    <div className="mt-3 ml-14 rounded-2xl overflow-hidden border border-violet-500/30 bg-gradient-to-br from-violet-950/70 to-purple-950/70 backdrop-blur-sm">
      {/* Top accent */}
      <div className="h-0.5 bg-gradient-to-r from-violet-500 to-pink-500" />

      <div className="p-4">
        <div className="flex items-start gap-3">
          <div className="w-9 h-9 shrink-0 rounded-xl bg-violet-500/20 border border-violet-500/30 flex items-center justify-center">
            <Zap size={18} className="text-violet-400" />
          </div>

          <div className="flex-1">
            <p className="text-white text-sm font-semibold leading-snug">
              Great! You've covered{' '}
              <span className="text-violet-300 bg-violet-500/15 px-1.5 py-0.5 rounded-lg">
                {topic}
              </span>
            </p>
            <p className="text-gray-400 text-xs mt-1">
              Test your understanding with a quick {numQuestions}-question quiz — takes under 5 minutes!
            </p>

            <div className="flex items-center gap-2 mt-3">
              <button
                onClick={onAccept}
                className="flex items-center gap-1.5 px-4 py-2 rounded-xl bg-gradient-to-r from-violet-600 to-purple-600 text-white text-sm font-semibold hover:from-violet-500 hover:to-purple-500 transition-all shadow-[0_4px_16px_rgba(139,92,246,0.3)]"
              >
                <Zap size={13} />
                Take Quiz ({numQuestions} Qs)
                <ChevronRight size={13} />
              </button>

              <button
                onClick={handleSkip}
                className="px-3 py-2 rounded-xl text-sm text-gray-400 border border-white/10 hover:bg-white/5 hover:text-gray-200 transition-all"
              >
                Skip
              </button>
            </div>
          </div>

          <button
            onClick={handleSkip}
            className="shrink-0 w-6 h-6 rounded-lg bg-white/5 border border-white/10 flex items-center justify-center text-gray-500 hover:text-white hover:bg-white/10 transition-all"
          >
            <X size={12} />
          </button>
        </div>
      </div>
    </div>
  );
}
