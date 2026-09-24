import React, { useState } from 'react';
import { CalendarClock, BookOpen, ChevronRight, X } from 'lucide-react';

/**
 * YesterdayContextBanner
 *
 * Shown at the top of chat (before any messages) on a new session when
 * the student had a session yesterday. Prompts them to take an assignment.
 *
 * Props:
 *   context    { subject, topic, session_date }
 *   onTake     () => void  — called when student clicks "Take Assignment"
 *   onDismiss  () => void  — called when student dismisses the banner
 */
export default function YesterdayContextBanner({ context, onTake, onDismiss }) {
  const [dismissed, setDismissed] = useState(false);

  if (!context || dismissed) return null;

  const handleDismiss = () => {
    setDismissed(true);
    if (onDismiss) onDismiss();
  };

  return (
    <div className="mx-4 mt-4 mb-2 rounded-2xl overflow-hidden border border-amber-500/30 bg-gradient-to-br from-amber-950/60 to-orange-950/60 backdrop-blur-sm animate-fade-in">
      {/* Top accent bar */}
      <div className="h-1 bg-gradient-to-r from-amber-400 via-orange-400 to-yellow-400" />

      <div className="p-4 flex items-start gap-4">
        {/* Icon */}
        <div className="w-10 h-10 shrink-0 rounded-xl bg-amber-500/20 border border-amber-500/30 flex items-center justify-center">
          <CalendarClock size={20} className="text-amber-400" />
        </div>

        {/* Content */}
        <div className="flex-1 min-w-0">
          <div className="flex items-center gap-2 mb-1">
            <span className="text-[10px] font-bold uppercase tracking-wider text-amber-400 bg-amber-500/15 px-2 py-0.5 rounded-full border border-amber-500/20">
              Yesterday's Session
            </span>
            <span className="text-xs text-gray-500">{context.session_date}</span>
          </div>

          <p className="text-white text-sm font-semibold leading-snug">
            You studied{' '}
            <span className="text-amber-300 bg-amber-500/15 px-1.5 py-0.5 rounded-lg">
              {context.topic}
            </span>
            {' '}in{' '}
            <span className="text-orange-300">{context.subject}</span>
          </p>
          <p className="text-gray-400 text-xs mt-1">
            Want to test your understanding with a quick assignment?
          </p>

          {/* CTA button */}
          <button
            onClick={onTake}
            className="mt-3 flex items-center gap-1.5 px-4 py-2 rounded-xl bg-gradient-to-r from-amber-500 to-orange-500 text-white text-sm font-semibold hover:from-amber-400 hover:to-orange-400 transition-all shadow-[0_4px_16px_rgba(245,158,11,0.3)] hover:shadow-[0_4px_20px_rgba(245,158,11,0.5)]"
          >
            <BookOpen size={14} />
            Take Assignment
            <ChevronRight size={14} />
          </button>
        </div>

        {/* Dismiss */}
        <button
          onClick={handleDismiss}
          className="shrink-0 w-7 h-7 rounded-lg bg-white/5 border border-white/10 flex items-center justify-center text-gray-400 hover:text-white hover:bg-white/10 transition-all"
        >
          <X size={14} />
        </button>
      </div>
    </div>
  );
}
