import React from 'react';
import { useAuth } from '../../context/AuthContext';
import { useSession } from '../../context/SessionContext';
import { LogOut, BrainCircuit, Activity, Clock, Zap, BookOpen } from 'lucide-react';

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

export default function Sidebar({ onStartQuiz }) {
  const { student, logout } = useAuth();
  const { 
    subject, setSubject, 
    tutorMode, setTutorMode,
    sessions, loadSession, sessionId,
    memory, sessionRemark
  } = useSession();

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

      <div className="p-5 space-y-8 flex-1">
        
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

        {/* Sessions */}
        <div>
          <div className="flex justify-between items-center mb-3">
            <label className="text-[10px] text-gray-400 uppercase font-extrabold tracking-widest flex items-center gap-1.5">
              <Clock size={12} className="text-blue-400" /> Past Sessions
            </label>
            <button onClick={() => loadSession('')} className="bg-indigo-500/20 hover:bg-indigo-500/40 text-indigo-300 px-3 py-1 rounded-full text-xs font-bold transition-all border border-indigo-500/30 hover:scale-105">
              + New
            </button>
          </div>
          <div className="space-y-1.5 max-h-48 overflow-y-auto pr-1">
            {sessions.map(s => (
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
                {/* Subtitle: date + message count */}
                <span className="text-[10px] opacity-50 flex items-center gap-1.5">
                  <Clock size={9} />
                  {new Date(s.created_at).toLocaleDateString('en-IN', { day: 'numeric', month: 'short' })}
                  {s.message_count > 0 && <span>· {s.message_count} msgs</span>}
                </span>
              </button>
            ))}
            {sessions.length === 0 && <div className="text-xs text-gray-500 italic p-2 bg-black/20 rounded-lg text-center">No past sessions</div>}
          </div>
        </div>

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
