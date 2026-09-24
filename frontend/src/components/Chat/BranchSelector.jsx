import React from 'react';
import { ChevronLeft, ChevronRight, GitBranch } from 'lucide-react';
import { useSession } from '../../context/SessionContext';

export default function BranchSelector({ siblingIds, siblingIndex, siblingCount }) {
  const { activateBranch } = useSession();

  if (!siblingIds || siblingCount <= 1) return null;

  const handlePrev = (e) => {
    e.stopPropagation();
    if (siblingIndex > 0) {
      activateBranch(siblingIds[siblingIndex - 1]);
    }
  };

  const handleNext = (e) => {
    e.stopPropagation();
    if (siblingIndex < siblingCount - 1) {
      activateBranch(siblingIds[siblingIndex + 1]);
    }
  };

  return (
    <div className="inline-flex items-center gap-1.5 px-2 py-0.5 rounded-full bg-black/40 border border-white/10 text-xs text-gray-300 select-none shadow-sm backdrop-blur-sm">
      <GitBranch size={11} className="text-indigo-400" />
      <button
        onClick={handlePrev}
        disabled={siblingIndex === 0}
        className="p-0.5 rounded hover:bg-white/10 disabled:opacity-30 disabled:cursor-not-allowed text-gray-300 hover:text-white transition-colors"
        title="Previous branch"
      >
        <ChevronLeft size={13} />
      </button>
      <span className="font-mono text-[11px] font-medium tracking-tight text-indigo-300">
        {siblingIndex + 1} / {siblingCount}
      </span>
      <button
        onClick={handleNext}
        disabled={siblingIndex === siblingCount - 1}
        className="p-0.5 rounded hover:bg-white/10 disabled:opacity-30 disabled:cursor-not-allowed text-gray-300 hover:text-white transition-colors"
        title="Next branch"
      >
        <ChevronRight size={13} />
      </button>
    </div>
  );
}
