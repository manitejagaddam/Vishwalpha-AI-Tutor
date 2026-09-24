import React, { useState, useEffect } from 'react';
import { useAuth } from '../../context/AuthContext';
import { useSession } from '../../context/SessionContext';
import { searchApi } from '../../api/client';
import { LogOut, BrainCircuit, Activity, Clock, Zap, BookOpen, Folder, Plus, Search, X } from 'lucide-react';
import StudySpaceModal from './StudySpaceModal';

/** Returns a human-readable session title from DB metadata */
function sessionTitle(s) {
  if (s.chat_title) return s.chat_title;
  if (s.last_topic_name) return s.last_topic_name;
  if (s.first_message_snippet) {
    return s.first_message_snippet.charAt(0).toUpperCase() + s.first_message_snippet.slice(1);
  }
  const date = new Date(s.created_at);
  const today = new Date();
  const yesterday = new Date();
  yesterday.setDate(today.getDate() - 1);
  if (date.toDateString() === today.toDateString()) return 'New Chat';
  if (date.toDateString() === yesterday.toDateString()) return 'Yesterday\'s Chat';
  return date.toLocaleDateString('en-IN', { day: 'numeric', month: 'short' }) + ' Chat';
}

export default function Sidebar({ onStartQuiz, onNewChat }) {
  const { student, logout } = useAuth();
  const { 
    subject, setSubject, 
    tutorMode, setTutorMode,
    sessions, loadSession, sessionId,
    studySpaces, activeSpaceId, setActiveSpaceId, activeSpace,
    memory, sessionRemark
  } = useSession();

  const [showSpaceModal, setShowSpaceModal] = useState(false);
  const [searchTerm, setSearchTerm] = useState('');
  const [searchResults, setSearchResults] = useState(null);
  const [isSearching, setIsSearching] = useState(false);

  // Search effect
  useEffect(() => {
    if (!searchTerm.trim()) {
      setSearchResults(null);
      setIsSearching(false);
      return;
    }

    const timer = setTimeout(async () => {
      setIsSearching(true);
      try {
        const res = await searchApi.searchConversations(searchTerm.trim());
        setSearchResults(res || []);
      } catch (err) {
        console.error('Search failed:', err);
      } finally {
        setIsSearching(false);
      }
    }, 300);

    return () => clearTimeout(timer);
  }, [searchTerm]);

  const displayedSessions = searchResults !== null 
    ? searchResults 
    : sessions;

  return (
    <div className="glass-panel flex flex-col h-full overflow-y-auto">
      {/* Profile Section */}
      <div className="p-5 border-b border-white/5 bg-gradient-to-b from-white/5 to-transparent">
        <div className="flex items-center justify-between">
          <div className="flex items-center gap-4">
            <div className="w-12 h-12 rounded-full bg-gradient-to-tr from-indigo-500 via-purple-500 to-pink-500 flex items-center justify-center text-xl font-bold shadow-[0_0_15px_rgba(99,102,241,0.5)] border border-white/20">
              {student.username[0].toUpperCase()}
            </div>
            <div>
              <div className="font-bold text-white text-lg tracking-wide">{student.username}</div>
              <div className="text-xs text-indigo-300 font-medium bg-indigo-500/10 px-2 py-0.5 rounded-full inline-block mt-1 border border-indigo-500/20">
                Class {student.class_num}
              </div>
            </div>
          </div>
          <button onClick={logout} className="p-2 hover:bg-white/10 rounded-full transition-all hover:scale-110 hover:text-pink-400" title="Logout">
            <LogOut size={18} className="text-gray-400 hover:text-pink-400" />
          </button>
        </div>
      </div>

      <div className="p-5 space-y-7 flex-1">
        
        {/* Study Space Switcher */}
        <div className="space-y-2">
          <div className="flex items-center justify-between">
            <label className="text-[10px] text-gray-400 uppercase font-extrabold tracking-widest flex items-center gap-1.5">
              <Folder size={12} className="text-violet-400" /> Study Space
            </label>
            <button
              onClick={() => setShowSpaceModal(true)}
              className="text-[11px] font-bold text-violet-300 hover:text-white flex items-center gap-1 hover:bg-violet-500/20 px-2 py-0.5 rounded-lg border border-violet-500/30 transition-all"
            >
              <Plus size={11} /> New Space
            </button>
          </div>

          <select
            value={activeSpaceId || ''}
            onChange={(e) => setActiveSpaceId(e.target.value ? e.target.value : null)}
            className="w-full bg-black/40 border border-white/10 rounded-xl p-2.5 text-xs font-semibold text-violet-200 focus:outline-none focus:ring-2 focus:ring-violet-500/50 appearance-none transition-all shadow-inner hover:bg-black/60"
          >
            <option value="">📂 All Workspaces</option>
            {studySpaces.map(sp => (
              <option key={sp.id} value={sp.id}>
                🎯 {sp.title}
              </option>
            ))}
          </select>

          {activeSpace && activeSpace.custom_instructions && (
            <div className="p-2.5 rounded-xl bg-violet-950/30 border border-violet-500/20 text-[11px] text-violet-300 leading-snug">
              <span className="font-bold text-violet-200">Custom focus: </span>
              {activeSpace.custom_instructions.length > 80
                ? activeSpace.custom_instructions.slice(0, 80) + '...'
                : activeSpace.custom_instructions}
            </div>
          )}
        </div>

        {/* Controls */}
        <div className="space-y-4">
          <div className="group">
            <label className="text-[10px] text-gray-400 uppercase font-extrabold tracking-widest mb-1.5 block group-hover:text-indigo-400 transition-colors">Subject Focus</label>
            <div className="relative">
              <select 
                value={subject}
                onChange={(e) => setSubject(e.target.value)}
                className="w-full bg-black/40 border border-white/10 rounded-xl p-3 text-sm font-medium focus:outline-none focus:ring-2 focus:ring-indigo-500/50 focus:border-indigo-500 appearance-none transition-all shadow-inner hover:bg-black/60"
              >
                <option value="Science">🧪 Science</option>
                <option value="Mathematics">📐 Mathematics</option>
                <option value="Social Science">🌍 Social Science</option>
              </select>
            </div>
          </div>
          
          <div className="group">
            <label className="text-[10px] text-gray-400 uppercase font-extrabold tracking-widest mb-1.5 block group-hover:text-purple-400 transition-colors">Learning Mode</label>
            <select 
              value={tutorMode}
              onChange={(e) => setTutorMode(e.target.value)}
              className="w-full bg-black/40 border border-white/10 rounded-xl p-3 text-sm font-medium focus:outline-none focus:ring-2 focus:ring-purple-500/50 focus:border-purple-500 appearance-none transition-all shadow-inner hover:bg-black/60"
            >
              <option value="standard">⚡ Standard Direct</option>
              <option value="deep">🧠 Deep Socratic</option>
            </select>
          </div>

          {/* Quick Quiz button */}
          <button
            onClick={() => onStartQuiz && onStartQuiz({ topic: '', subject })}
            className="w-full flex items-center justify-center gap-2 py-3 px-4 rounded-xl bg-gradient-to-r from-violet-600/30 to-purple-600/30 border border-violet-500/40 text-violet-300 text-sm font-bold hover:from-violet-600/60 hover:to-purple-600/60 hover:text-white transition-all shadow-[0_0_20px_rgba(139,92,246,0.15)] hover:shadow-[0_0_20px_rgba(139,92,246,0.35)] group"
          >
            <Zap size={15} className="group-hover:text-yellow-300 transition-colors" />
            Take a Quiz
          </button>
        </div>

        {/* Sessions & Search */}
        <div>
          <div className="flex justify-between items-center mb-2.5">
            <label className="text-[10px] text-gray-400 uppercase font-extrabold tracking-widest flex items-center gap-1.5">
              <Clock size={12} className="text-blue-400" /> Past Sessions
            </label>
            <button
              onClick={() => {
                if (onNewChat) onNewChat();
                loadSession('');
              }}
              className="bg-indigo-500/20 hover:bg-indigo-500/40 text-indigo-300 px-3 py-1 rounded-full text-xs font-bold transition-all border border-indigo-500/30 hover:scale-105"
            >
              + New
            </button>
          </div>

          {/* Search Bar */}
          <div className="relative mb-3">
            <Search size={13} className="absolute left-3 top-3 text-gray-400 pointer-events-none" />
            <input
              type="text"
              placeholder="Search chats or topics..."
              value={searchTerm}
              onChange={(e) => setSearchTerm(e.target.value)}
              className="w-full bg-black/40 border border-white/10 rounded-xl pl-8 pr-7 py-2 text-xs text-white placeholder-gray-500 focus:outline-none focus:ring-1 focus:ring-indigo-500/50"
            />
            {searchTerm && (
              <button
                onClick={() => setSearchTerm('')}
                className="absolute right-2.5 top-2.5 text-gray-400 hover:text-white"
              >
                <X size={13} />
              </button>
            )}
          </div>

          <div className="space-y-1.5 max-h-48 overflow-y-auto pr-1">
            {displayedSessions.map(s => (
              <button
                key={s.id}
                onClick={() => loadSession(s.id)}
                className={`w-full text-left p-3 rounded-xl text-sm transition-all flex flex-col gap-0.5 border ${
                  s.id === sessionId 
                    ? 'bg-gradient-to-r from-indigo-600/30 to-purple-600/10 border-indigo-500/50 text-white shadow-[inset_0_0_10px_rgba(99,102,241,0.2)]' 
                    : 'bg-black/20 border-transparent text-gray-400 hover:bg-white/5 hover:border-white/10 hover:text-gray-200'
                }`}
              >
                {/* Smart title: topic name if available, else friendly date */}
                <span className="font-medium truncate leading-tight">{sessionTitle(s)}</span>
                
                {/* Match snippet if from search */}
                {s.match_snippet && s.match_type === 'message' && (
                  <span className="text-[11px] text-indigo-300/80 truncate italic">
                    "{s.match_snippet}"
                  </span>
                )}

                {/* Subtitle: date + message count */}
                <span className="text-[10px] opacity-50 flex items-center gap-1.5">
                  <Clock size={9} />
                  {new Date(s.created_at).toLocaleDateString('en-IN', { day: 'numeric', month: 'short' })}
                  {s.message_count > 0 && <span>· {s.message_count} msgs</span>}
                </span>
              </button>
            ))}
            {displayedSessions.length === 0 && (
              <div className="text-xs text-gray-500 italic p-3 bg-black/20 rounded-lg text-center">
                {searchTerm ? 'No matching conversations' : 'No past sessions'}
              </div>
            )}
          </div>
        </div>

        {/* Study Space Modal */}
        {showSpaceModal && (
          <StudySpaceModal onClose={() => setShowSpaceModal(false)} />
        )}

        {/* Remarks */}
        {sessionRemark && (
          <div className="glass-card p-4 rounded-xl relative overflow-hidden group">
            <div className="absolute top-0 right-0 w-16 h-16 bg-blue-500/10 rounded-bl-full -z-10 group-hover:scale-150 transition-transform duration-500" />
            <div className="text-xs text-blue-300 font-extrabold mb-2 flex items-center gap-1.5 uppercase tracking-wide">
              <Activity size={14} />
              Session Insights
            </div>
            <div className="text-sm text-gray-200 leading-relaxed font-medium">{sessionRemark}</div>
          </div>
        )}

        {/* Memory */}
        <div className="pb-4">
          <label className="text-[10px] text-emerald-400 uppercase font-extrabold tracking-widest mb-3 flex items-center gap-1.5">
            <BrainCircuit size={14} />
            Long-term Memory
          </label>
          <div className="bg-black/30 border border-emerald-500/20 p-4 rounded-xl text-sm text-gray-300 max-h-48 overflow-y-auto whitespace-pre-wrap shadow-inner leading-relaxed relative group">
            <div className="absolute top-0 left-0 w-full h-1 bg-gradient-to-r from-emerald-500/50 to-transparent opacity-0 group-hover:opacity-100 transition-opacity" />
            {memory || <span className="text-gray-500 italic">No memory data yet...</span>}
          </div>
        </div>

      </div>
    </div>
  );
}
