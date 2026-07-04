import React from 'react';
import { useAuth } from '../../context/AuthContext';
import { useSession } from '../../context/SessionContext';
import { LogOut, BookOpen, BrainCircuit, Activity, RefreshCw } from 'lucide-react';

export default function Sidebar() {
  const { student, logout } = useAuth();
  const { 
    subject, setSubject, 
    tutorMode, setTutorMode,
    sessions, loadSession, sessionId,
    memory,
    metrics, cognitiveSkills,
    sessionRemark
  } = useSession();

  return (
    <div className="w-80 bg-white/5 border-r border-white/10 flex flex-col h-full overflow-y-auto backdrop-blur-xl">
      <div className="p-4 border-b border-white/10 flex items-center justify-between">
        <div className="flex items-center gap-3">
          <div className="w-10 h-10 rounded-full bg-gradient-to-br from-indigo-500 to-purple-600 flex items-center justify-center text-lg font-bold shadow-lg">
            {student.username[0].toUpperCase()}
          </div>
          <div>
            <div className="font-semibold">{student.username}</div>
            <div className="text-xs text-gray-400">Class {student.class_num}</div>
          </div>
        </div>
        <button onClick={logout} className="p-2 hover:bg-white/10 rounded-full transition-colors" title="Logout">
          <LogOut size={18} className="text-gray-400" />
        </button>
      </div>

      <div className="p-4 space-y-6 flex-1">
        
        {/* Controls */}
        <div className="space-y-3">
          <div>
            <label className="text-xs text-gray-400 uppercase font-semibold tracking-wider">Subject</label>
            <select 
              value={subject}
              onChange={(e) => setSubject(e.target.value)}
              className="w-full mt-1 bg-white/5 border border-white/10 rounded-lg p-2 text-sm focus:outline-none focus:border-indigo-500"
            >
              <option value="Science">Science</option>
              <option value="Mathematics">Mathematics</option>
              <option value="Social Science">Social Science</option>
            </select>
          </div>
          
          <div>
            <label className="text-xs text-gray-400 uppercase font-semibold tracking-wider">Tutor Mode</label>
            <select 
              value={tutorMode}
              onChange={(e) => setTutorMode(e.target.value)}
              className="w-full mt-1 bg-white/5 border border-white/10 rounded-lg p-2 text-sm focus:outline-none focus:border-indigo-500"
            >
              <option value="standard">Standard</option>
              <option value="deep">Deep Learning (Socratic)</option>
            </select>
          </div>
        </div>

        {/* Sessions */}
        <div>
          <label className="text-xs text-gray-400 uppercase font-semibold tracking-wider flex justify-between items-center mb-2">
            <span>Past Sessions</span>
            <button onClick={() => loadSession('')} className="text-indigo-400 hover:text-indigo-300 normal-case text-xs">
              + New Session
            </button>
          </label>
          <div className="space-y-1 max-h-40 overflow-y-auto pr-1">
            {sessions.map(s => (
              <button
                key={s.id}
                onClick={() => loadSession(s.id)}
                className={`w-full text-left p-2 rounded text-sm truncate ${s.id === sessionId ? 'bg-indigo-500/20 text-indigo-300' : 'hover:bg-white/5 text-gray-300'}`}
              >
                {new Date(s.created_at).toLocaleDateString()} - {s.subject}
              </button>
            ))}
            {sessions.length === 0 && <div className="text-xs text-gray-500 italic">No past sessions</div>}
          </div>
        </div>

        {/* Remarks */}
        {sessionRemark && (
          <div className="bg-indigo-500/10 border border-indigo-500/20 p-3 rounded-lg">
            <div className="text-xs text-indigo-300 font-semibold mb-1 flex items-center gap-1">
              <Activity size={12} />
              Session Insights
            </div>
            <div className="text-xs text-gray-300">{sessionRemark}</div>
          </div>
        )}

        {/* Memory */}
        <div>
          <label className="text-xs text-gray-400 uppercase font-semibold tracking-wider mb-2 block flex items-center gap-1">
            <BrainCircuit size={14} />
            Learning Memory
          </label>
          <div className="bg-white/5 border border-white/10 p-3 rounded-lg text-xs text-gray-300 max-h-40 overflow-y-auto whitespace-pre-wrap">
            {memory || <span className="text-gray-500 italic">No memory data yet...</span>}
          </div>
        </div>

      </div>
    </div>
  );
}
