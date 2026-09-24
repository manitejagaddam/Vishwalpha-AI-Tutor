import React, { useState } from 'react';
import { spacesApi } from '../../api/client';
import { useSession } from '../../context/SessionContext';
import { FolderPlus, X, Sparkles } from 'lucide-react';

export default function StudySpaceModal({ onClose, onCreated }) {
  const { subject, refreshSpaces, setActiveSpaceId } = useSession();
  const [title, setTitle] = useState('');
  const [spaceSubject, setSpaceSubject] = useState(subject || 'Science');
  const [instructions, setInstructions] = useState('');
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [error, setError] = useState('');

  const handleSubmit = async (e) => {
    e.preventDefault();
    if (!title.trim()) return;

    setIsSubmitting(true);
    setError('');
    try {
      const space = await spacesApi.createSpace({
        title: title.trim(),
        subject: spaceSubject,
        custom_instructions: instructions.trim() || null,
      });
      await refreshSpaces();
      if (space?.id) {
        setActiveSpaceId(space.id);
      }
      if (onCreated) onCreated(space);
      onClose();
    } catch (err) {
      setError(err.response?.data?.detail || err.message || 'Failed to create workspace');
    } finally {
      setIsSubmitting(false);
    }
  };

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-black/70 backdrop-blur-md animate-fade-in">
      <div className="relative w-full max-w-md bg-gray-950/90 border border-white/10 rounded-3xl p-6 shadow-[0_0_50px_rgba(99,102,241,0.25)] text-white">
        
        {/* Close Button */}
        <button
          onClick={onClose}
          className="absolute top-5 right-5 p-2 rounded-full hover:bg-white/10 text-gray-400 hover:text-white transition-colors"
        >
          <X size={18} />
        </button>

        {/* Header */}
        <div className="flex items-center gap-3 mb-5">
          <div className="w-10 h-10 rounded-2xl bg-gradient-to-tr from-violet-500 to-indigo-600 flex items-center justify-center shadow-lg shadow-indigo-500/20">
            <FolderPlus size={20} className="text-white" />
          </div>
          <div>
            <h3 className="text-lg font-bold">New Study Space</h3>
            <p className="text-xs text-gray-400">Custom curriculum workspace for focused prep</p>
          </div>
        </div>

        {error && (
          <div className="mb-4 p-3 rounded-xl bg-red-500/10 border border-red-500/30 text-red-300 text-xs">
            {error}
          </div>
        )}

        <form onSubmit={handleSubmit} className="space-y-4">
          <div>
            <label className="text-[11px] uppercase font-bold text-gray-400 tracking-wider mb-1 block">
              Workspace Title
            </label>
            <input
              type="text"
              required
              placeholder="e.g. CBSE 10th Board Exam Numerical Prep"
              value={title}
              onChange={(e) => setTitle(e.target.value)}
              className="w-full bg-black/60 border border-white/10 rounded-xl px-4 py-3 text-sm text-white placeholder-gray-500 focus:outline-none focus:ring-2 focus:ring-indigo-500/50"
            />
          </div>

          <div>
            <label className="text-[11px] uppercase font-bold text-gray-400 tracking-wider mb-1 block">
              Subject
            </label>
            <select
              value={spaceSubject}
              onChange={(e) => setSpaceSubject(e.target.value)}
              className="w-full bg-black/60 border border-white/10 rounded-xl px-4 py-3 text-sm text-white focus:outline-none focus:ring-2 focus:ring-indigo-500/50"
            >
              <option value="Science">🧪 Science</option>
              <option value="Mathematics">📐 Mathematics</option>
              <option value="Social Science">🌍 Social Science</option>
            </select>
          </div>

          <div>
            <label className="text-[11px] uppercase font-bold text-gray-400 tracking-wider mb-1 block flex items-center justify-between">
              <span>Custom Tutoring Instructions</span>
              <span className="text-[10px] text-gray-500 lowercase font-normal">(optional)</span>
            </label>
            <textarea
              rows={3}
              placeholder="e.g. 'Focus on step-by-step NCERT formula derivations and test me on chemical equations after each concept.'"
              value={instructions}
              onChange={(e) => setInstructions(e.target.value)}
              className="w-full bg-black/60 border border-white/10 rounded-xl px-4 py-3 text-sm text-white placeholder-gray-500 focus:outline-none focus:ring-2 focus:ring-indigo-500/50 resize-none leading-relaxed"
            />
          </div>

          <div className="flex justify-end gap-2 pt-3 border-t border-white/5">
            <button
              type="button"
              onClick={onClose}
              className="px-4 py-2.5 rounded-xl text-xs font-semibold text-gray-400 hover:text-white hover:bg-white/5 transition-colors"
            >
              Cancel
            </button>
            <button
              type="submit"
              disabled={isSubmitting || !title.trim()}
              className="px-5 py-2.5 rounded-xl bg-gradient-to-r from-indigo-600 to-purple-600 hover:from-indigo-500 hover:to-purple-500 text-white font-medium text-xs shadow-lg shadow-indigo-600/30 transition-all disabled:opacity-50"
            >
              {isSubmitting ? 'Creating...' : 'Create Space'}
            </button>
          </div>
        </form>
      </div>
    </div>
  );
}
