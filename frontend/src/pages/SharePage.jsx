import React, { useState, useEffect } from 'react';
import { useParams, Link } from 'react-router-dom';
import { shareApi } from '../api/client';
import ReactMarkdown from 'react-markdown';
import remarkGfm from 'remark-gfm';
import { Sparkles, Calendar, BookOpen, ExternalLink, ArrowRight, ShieldCheck } from 'lucide-react';

export default function SharePage() {
  const { token } = useParams();
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');

  useEffect(() => {
    if (!token) return;
    setLoading(true);
    setError('');
    shareApi.getSharedConversation(token)
      .then((res) => {
        setData(res);
      })
      .catch((err) => {
        setError(err.response?.data?.detail || err.message || 'Shared link not found or expired.');
      })
      .finally(() => setLoading(false));
  }, [token]);

  if (loading) {
    return (
      <div className="min-h-screen bg-slate-950 flex flex-col items-center justify-center text-white">
        <div className="w-12 h-12 border-3 border-indigo-400 border-t-transparent rounded-full animate-spin mb-4" />
        <p className="text-gray-400 text-sm font-medium animate-pulse">Loading shared session...</p>
      </div>
    );
  }

  if (error || !data) {
    return (
      <div className="min-h-screen bg-slate-950 flex flex-col items-center justify-center p-6 text-white text-center">
        <div className="w-16 h-16 rounded-full bg-red-500/20 border border-red-500/30 flex items-center justify-center text-red-400 text-2xl mb-4">
          ⚠️
        </div>
        <h2 className="text-xl font-bold mb-2">Snapshot Unavailable</h2>
        <p className="text-gray-400 max-w-sm text-sm mb-6">{error || 'This conversation link is either invalid or has expired.'}</p>
        <Link
          to="/"
          className="px-5 py-2.5 rounded-xl bg-indigo-600 hover:bg-indigo-500 text-white font-medium text-sm transition-all"
        >
          Go to VishwAlpha Home
        </Link>
      </div>
    );
  }

  const { title, subject, student_class, created_at, messages = [] } = data;

  return (
    <div className="min-h-screen bg-gradient-to-b from-slate-950 via-gray-900 to-black text-gray-100 flex flex-col">
      {/* Top Navbar */}
      <header className="border-b border-white/10 bg-black/40 backdrop-blur-xl sticky top-0 z-20 px-6 py-4 flex items-center justify-between">
        <div className="flex items-center gap-3">
          <div className="w-9 h-9 rounded-xl bg-gradient-to-tr from-indigo-500 to-purple-600 flex items-center justify-center shadow-lg shadow-indigo-500/20">
            <Sparkles size={18} className="text-white" />
          </div>
          <div>
            <h1 className="font-extrabold text-base tracking-tight bg-clip-text text-transparent bg-gradient-to-r from-indigo-400 via-purple-400 to-pink-400">
              VishwAlpha AI Tutor
            </h1>
            <span className="text-[10px] text-gray-400 font-medium">Read-Only Shared Session</span>
          </div>
        </div>

        <Link
          to="/"
          className="flex items-center gap-2 px-4 py-2 rounded-xl bg-gradient-to-r from-indigo-600 to-purple-600 hover:from-indigo-500 hover:to-purple-500 text-white text-xs font-bold transition-all shadow-md shadow-indigo-600/30 hover:scale-105 active:scale-95"
        >
          <span>Ask Your Own Questions</span>
          <ArrowRight size={14} />
        </Link>
      </header>

      {/* Main Container */}
      <main className="flex-1 max-w-4xl w-full mx-auto p-6 md:p-10 space-y-6">
        
        {/* Session Card Banner */}
        <div className="p-6 rounded-3xl bg-white/5 border border-white/10 shadow-2xl backdrop-blur-xl relative overflow-hidden">
          <div className="absolute top-0 right-0 w-64 h-64 bg-indigo-500/10 rounded-full blur-3xl pointer-events-none" />
          <div className="flex flex-wrap items-center gap-2.5 mb-3">
            <span className="px-3 py-1 rounded-full text-xs font-semibold bg-indigo-500/20 text-indigo-300 border border-indigo-500/30 flex items-center gap-1.5">
              <BookOpen size={12} /> {subject || 'Science'}
            </span>
            {student_class && (
              <span className="px-3 py-1 rounded-full text-xs font-semibold bg-purple-500/20 text-purple-300 border border-purple-500/30">
                Class {student_class}
              </span>
            )}
            <span className="px-3 py-1 rounded-full text-xs font-medium bg-white/5 text-gray-400 border border-white/5 flex items-center gap-1.5">
              <ShieldCheck size={12} className="text-emerald-400" /> Verified NCERT Grounding
            </span>
          </div>
          <h2 className="text-2xl md:text-3xl font-extrabold text-white tracking-tight">{title}</h2>
          {created_at && (
            <p className="text-xs text-gray-400 mt-2 flex items-center gap-1.5 font-medium">
              <Calendar size={12} />
              Shared on {new Date(created_at).toLocaleDateString('en-IN', { day: 'numeric', month: 'long', year: 'numeric' })}
            </p>
          )}
        </div>

        {/* Message Stream */}
        <div className="space-y-6 pt-2">
          {messages.map((msg, i) => (
            <div key={i} className={`flex ${msg.role === 'student' ? 'justify-end' : 'justify-start'}`}>
              <div className={`max-w-[88%] flex gap-4 ${msg.role === 'student' ? 'flex-row-reverse' : 'flex-row'} items-start`}>
                
                <div className={`w-10 h-10 rounded-2xl flex items-center justify-center text-lg shrink-0 shadow-lg border border-white/10 ${
                  msg.role === 'student'
                    ? 'bg-gradient-to-br from-indigo-500 to-purple-600'
                    : 'bg-gradient-to-br from-teal-500 to-emerald-600'
                }`}>
                  {msg.role === 'student' ? '👤' : '🤖'}
                </div>

                <div className={`p-5 text-[15px] leading-relaxed shadow-xl ${
                  msg.role === 'student'
                    ? 'bg-gradient-to-br from-indigo-600 to-purple-700 text-white rounded-3xl rounded-br-sm shadow-[0_4px_20px_rgba(99,102,241,0.3)]'
                    : 'bg-gray-900/80 border border-white/10 text-gray-100 rounded-3xl rounded-bl-sm shadow-xl backdrop-blur-md'
                }`}>
                  <div className={`markdown-content [&_h1]:text-2xl [&_h1]:font-bold [&_h1]:mb-3 [&_h2]:text-xl [&_h2]:font-bold [&_h2]:mt-5 [&_h2]:mb-2 [&_h3]:text-lg [&_h3]:font-semibold [&_p]:mb-3 [&_ul]:list-disc [&_ul]:pl-5 [&_ul]:mb-3 [&_ol]:list-decimal [&_ol]:pl-5 [&_ol]:mb-3 [&_li]:mb-1 [&_table]:w-full [&_table]:border-collapse [&_table]:mb-4 [&_table]:text-sm [&_th]:border [&_th]:border-white/20 [&_th]:p-2 [&_th]:bg-white/10 [&_td]:border [&_td]:border-white/10 [&_td]:p-2 [&_blockquote]:border-l-4 [&_blockquote]:border-indigo-400 [&_blockquote]:pl-4 [&_blockquote]:italic [&_blockquote]:text-gray-300 [&_strong]:font-bold [&_code]:bg-black/30 [&_code]:px-1.5 [&_code]:py-0.5 [&_code]:rounded text-[15px] leading-relaxed ${
                    msg.role === 'student' ? '[&_strong]:text-white' : '[&_strong]:text-indigo-200'
                  }`}>
                    <ReactMarkdown remarkPlugins={[remarkGfm]}>
                      {msg.content}
                    </ReactMarkdown>
                  </div>
                </div>

              </div>
            </div>
          ))}
        </div>

        {/* Bottom CTA Banner */}
        <div className="mt-12 p-8 rounded-3xl bg-gradient-to-r from-indigo-900/40 via-purple-900/40 to-pink-900/20 border border-indigo-500/20 text-center space-y-4">
          <h3 className="text-xl font-bold text-white">Study Smarter with VishwAlpha</h3>
          <p className="text-sm text-gray-300 max-w-md mx-auto">
            Get instant textbook answers, personalized spaced-repetition quizzes, and cognitive mastery tracking.
          </p>
          <div>
            <Link
              to="/"
              className="inline-flex items-center gap-2 px-6 py-3 rounded-2xl bg-gradient-to-r from-indigo-500 to-purple-600 text-white font-bold text-sm shadow-xl shadow-indigo-500/30 hover:scale-105 transition-transform"
            >
              <span>Get Started for Free</span>
              <Sparkles size={16} />
            </Link>
          </div>
        </div>

      </main>
    </div>
  );
}
