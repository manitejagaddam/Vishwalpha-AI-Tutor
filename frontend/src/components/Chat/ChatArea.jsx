import React, { useState, useEffect, useRef } from 'react';
import { useAuth } from '../../context/AuthContext';
import { useSession } from '../../context/SessionContext';
import { chatApi } from '../../api/client';
import { Send, Sparkles } from 'lucide-react';
import ReactMarkdown from 'react-markdown';
import remarkGfm from 'remark-gfm';

import QuizCard from '../Quiz/QuizCard';
import QuizSuggestionCard from '../Quiz/QuizSuggestionCard';
import YesterdayContextBanner from '../Quiz/YesterdayContextBanner';

export default function ChatArea() {
  const { student } = useAuth();
  const {
    sessionId, setSessionId,
    messages, setMessages,
    subject, tutorMode,
    refreshSessions, refreshProfile, refreshMemory,
    setMetricsAdjustments, setSessionRemark
  } = useSession();

  const [input, setInput] = useState('');
  const [isThinking, setIsThinking] = useState(false);
  const scrollRef = useRef(null);

  // ── Quiz state ──────────────────────────────────────────────────────────────
  // yesterdayCtx: { subject, topic, session_date } | null
  const [yesterdayCtx, setYesterdayCtx] = useState(null);
  const [yesterdayBannerDismissed, setYesterdayBannerDismissed] = useState(false);

  // activeQuiz: { topic, subject, source, sessionId } | null — triggers QuizCard overlay
  const [activeQuiz, setActiveQuiz] = useState(null);

  // Per-message quiz suggestions: { [msgIndex]: { topic, subject, numQuestions } }
  const [quizSuggestions, setQuizSuggestions] = useState({});
  // Set of message indices where quiz suggestion has been accepted/skipped
  const [dismissedSuggestions, setDismissedSuggestions] = useState(new Set());

  // Auto-scroll on new messages
  useEffect(() => {
    if (scrollRef.current) {
      scrollRef.current.scrollTop = scrollRef.current.scrollHeight;
    }
  }, [messages, isThinking, activeQuiz]);

  // When sessionId clears (new session), pick up yesterday context from first chat response
  // (The backend sends it in is_session_start=true responses)
  const yesterdayCtxSetRef = useRef(false);

  const handleSend = async (e) => {
    e.preventDefault();
    if (!input.trim()) return;

    const questionText = input.trim();
    setInput('');

    // Optimistic append
    const newMsg = { role: 'student', content: questionText };
    setMessages(prev => [...prev, newMsg]);
    setIsThinking(true);

    try {
      const response = await chatApi.sendMessage({
        student_id: student.student_id,
        session_id: sessionId,
        question: questionText,
        subject: subject,
        tutor_mode: tutorMode
      });

      if (!sessionId && response.session_id) {
        setSessionId(response.session_id);
        refreshSessions();
      }

      // Pick up yesterday context on new session (first response)
      if (response.is_session_start && response.yesterday_context && !yesterdayCtxSetRef.current) {
        setYesterdayCtx(response.yesterday_context);
        yesterdayCtxSetRef.current = true;
      }

      const tutorMsg = {
        role: 'tutor',
        content: response.answer,
        sources: response.sources,
        chapter: response.routed_chapter,
        topic: response.routed_topic,
        question_type: response.question_type,
        chunks: response.raw_chunks,
        prompt_messages: response.prompt_messages,
        quiz_suggestion: response.quiz_suggestion || null,
      };

      setMessages(prev => {
        const updated = [...prev, tutorMsg];
        // Store quiz suggestion keyed by message index
        if (response.quiz_suggestion) {
          setQuizSuggestions(old => ({ ...old, [updated.length - 1]: response.quiz_suggestion }));
        }
        return updated;
      });

      if (response.metrics_adjustments) {
        setMetricsAdjustments(response.metrics_adjustments);
      }

      refreshProfile();
      refreshMemory();

    } catch (e) {
      setMessages(prev => [...prev, {
        role: 'tutor',
        content: `⚠️ Error: ${e.response?.data?.detail || e.message}`
      }]);
    } finally {
      setIsThinking(false);
    }
  };

  // ── Quiz handlers ──────────────────────────────────────────────────────────

  const startQuiz = ({ topic, subject: sub, source = 'manual' }) => {
    setActiveQuiz({
      topic,
      subject: sub || subject,
      source,
      sessionId: sessionId || '',
    });
    setYesterdayBannerDismissed(true);
  };

  const handleQuizSuggestionAccept = (msgIndex) => {
    const suggestion = quizSuggestions[msgIndex];
    if (!suggestion) return;
    setDismissedSuggestions(prev => new Set([...prev, msgIndex]));
    startQuiz({ topic: suggestion.topic, subject: suggestion.subject, source: 'mid_concept' });
  };

  const handleQuizSuggestionSkip = (msgIndex) => {
    setDismissedSuggestions(prev => new Set([...prev, msgIndex]));
  };

  const handleYesterdayTake = () => {
    if (!yesterdayCtx) return;
    startQuiz({ topic: yesterdayCtx.topic, subject: yesterdayCtx.subject, source: 'yesterday' });
  };

  const handleQuizClose = () => {
    setActiveQuiz(null);
    refreshProfile();
    refreshMemory();
  };

  // ── Render ─────────────────────────────────────────────────────────────────

  return (
    <div className="flex flex-col h-full bg-black/20 backdrop-blur-sm relative z-0">

      {/* Header */}
      <div className="p-5 text-center border-b border-white/5 bg-gradient-to-b from-black/60 to-transparent sticky top-0 z-10 backdrop-blur-md">
        <h1 className="text-2xl font-black tracking-tight flex items-center justify-center gap-2">
          <Sparkles className="text-indigo-400" size={24} />
          <span className="bg-clip-text text-transparent bg-gradient-to-r from-indigo-400 via-purple-400 to-pink-400 drop-shadow-[0_0_10px_rgba(168,85,247,0.4)]">
            VishwAlpha AI Tutor
          </span>
        </h1>
        <p className="text-xs text-gray-400 mt-1 font-medium tracking-wide">Personalised NCERT curriculum assistant</p>
      </div>

      {/* Messages */}
      <div className="flex-1 overflow-y-auto p-6 space-y-4" ref={scrollRef}>

        {/* Yesterday Context Banner — shown before any messages on new session */}
        {yesterdayCtx && !yesterdayBannerDismissed && (
          <YesterdayContextBanner
            context={yesterdayCtx}
            onTake={handleYesterdayTake}
            onDismiss={() => setYesterdayBannerDismissed(true)}
          />
        )}

        {/* Active Quiz — shown inline above input */}
        {activeQuiz && (
          <QuizCard
            topic={activeQuiz.topic}
            subject={activeQuiz.subject}
            source={activeQuiz.source}
            sessionId={activeQuiz.sessionId}
            numQuestions={7}
            onClose={handleQuizClose}
          />
        )}

        {/* Empty state */}
        {messages.length === 0 && !yesterdayCtx && (
          <div className="flex flex-col items-center justify-center h-full text-center mt-[-40px]">
            <div className="w-24 h-24 bg-gradient-to-br from-indigo-500/20 to-purple-500/20 rounded-full flex items-center justify-center mb-6 shadow-[0_0_40px_rgba(99,102,241,0.2)] border border-indigo-500/20">
              <Sparkles className="text-indigo-400 w-10 h-10" />
            </div>
            <h2 className="text-3xl font-bold mb-3 text-white">Namaste, {student.username}!</h2>
            <p className="text-gray-400 text-lg max-w-md mx-auto leading-relaxed">
              I'm VishwAlpha. I see you're using <strong className="text-indigo-400 bg-indigo-500/10 px-2 py-0.5 rounded">{tutorMode === 'standard' ? 'Standard' : 'Deep Learning'}</strong> mode for {subject}.
            </p>
            <p className="text-gray-500 mt-6 font-medium">What would you like to learn today?</p>
          </div>
        )}

        {/* Message list */}
        {messages.map((msg, i) => (
          <div key={i}>
            <div className={`flex ${msg.role === 'student' ? 'justify-end' : 'justify-start'}`}>
              <div className={`max-w-[85%] flex gap-4 ${msg.role === 'student' ? 'flex-row-reverse' : 'flex-row'} items-end`}>

                <div className={`w-10 h-10 rounded-2xl flex items-center justify-center text-lg shrink-0 shadow-lg border border-white/10 relative z-10 ${
                  msg.role === 'student'
                    ? 'bg-gradient-to-br from-indigo-500 to-purple-600'
                    : 'bg-gradient-to-br from-teal-500 to-emerald-600'
                }`}>
                  {msg.role === 'student' ? '👤' : '🤖'}
                </div>

                <div className={`p-5 text-[15px] leading-relaxed shadow-xl ${
                  msg.role === 'student'
                    ? 'bg-gradient-to-br from-indigo-600 to-purple-700 text-white rounded-3xl rounded-br-sm shadow-[0_4px_20px_rgba(99,102,241,0.3)]'
                    : 'glass-card text-gray-100 rounded-3xl rounded-bl-sm border-white/5'
                }`}>

                  {msg.role === 'tutor' && (
                    <div className="mb-3 flex items-center gap-2">
                      <span className={`text-[10px] font-bold px-2.5 py-1 rounded-full uppercase tracking-wider ${
                        msg.question_type === 'conversational'
                          ? 'bg-emerald-500/20 text-emerald-400 border border-emerald-500/30 shadow-[0_0_10px_rgba(16,185,129,0.2)]'
                          : 'bg-indigo-500/20 text-indigo-400 border border-indigo-500/30 shadow-[0_0_10px_rgba(99,102,241,0.2)]'
                      }`}>
                        {msg.question_type === 'conversational' ? '💬 Conversational' : '📚 Curriculum'}
                      </span>
                    </div>
                  )}

                  <div className={`markdown-content [&_h1]:text-2xl [&_h1]:font-bold [&_h1]:mb-3 [&_h2]:text-xl [&_h2]:font-bold [&_h2]:mt-5 [&_h2]:mb-2 [&_h3]:text-lg [&_h3]:font-semibold [&_p]:mb-3 [&_ul]:list-disc [&_ul]:pl-5 [&_ul]:mb-3 [&_ol]:list-decimal [&_ol]:pl-5 [&_ol]:mb-3 [&_li]:mb-1 [&_table]:w-full [&_table]:border-collapse [&_table]:mb-4 [&_table]:text-sm [&_th]:border [&_th]:border-white/20 [&_th]:p-2 [&_th]:bg-white/10 [&_td]:border [&_td]:border-white/10 [&_td]:p-2 [&_blockquote]:border-l-4 [&_blockquote]:border-indigo-400 [&_blockquote]:pl-4 [&_blockquote]:italic [&_blockquote]:text-gray-300 [&_strong]:font-bold [&_code]:bg-black/30 [&_code]:px-1.5 [&_code]:py-0.5 [&_code]:rounded text-[15px] leading-relaxed ${msg.role === 'student' ? '[&_strong]:text-white' : '[&_strong]:text-indigo-200'}`}>
                    <ReactMarkdown remarkPlugins={[remarkGfm]}>
                      {msg.content}
                    </ReactMarkdown>
                  </div>

                  {msg.sources && msg.sources.length > 0 && (
                    <div className="mt-4 pt-3 border-t border-white/10 flex flex-wrap gap-2">
                      {msg.sources.map((s, idx) => (
                        <span key={idx} className="bg-black/40 border border-white/5 text-gray-400 text-xs px-2.5 py-1 rounded-lg flex items-center gap-1.5 hover:bg-black/60 transition-colors">
                          <span className="text-indigo-400">📚</span> {s.topic} <span className="opacity-50">({(s.score).toFixed(2)})</span>
                        </span>
                      ))}
                    </div>
                  )}
                </div>
              </div>
            </div>

            {/* Quiz Suggestion Card — right after tutor messages that triggered concept completion */}
            {msg.role === 'tutor' && quizSuggestions[i] && !dismissedSuggestions.has(i) && !activeQuiz && (
              <QuizSuggestionCard
                topic={quizSuggestions[i].topic}
                subject={quizSuggestions[i].subject}
                numQuestions={quizSuggestions[i].num_questions}
                onAccept={() => handleQuizSuggestionAccept(i)}
                onSkip={() => handleQuizSuggestionSkip(i)}
              />
            )}
          </div>
        ))}

        {/* Thinking indicator */}
        {isThinking && (
          <div className="flex justify-start">
            <div className="flex gap-4 max-w-[80%] items-end">
              <div className="w-10 h-10 rounded-2xl bg-gradient-to-br from-teal-500 to-emerald-600 border border-white/10 flex items-center justify-center text-lg shadow-lg relative z-10">🤖</div>
              <div className="glass-card p-5 rounded-3xl rounded-bl-sm text-gray-200 flex gap-1.5 items-center h-[60px] border-white/5">
                <div className="w-2.5 h-2.5 bg-indigo-400 rounded-full animate-bounce shadow-[0_0_8px_rgba(129,140,248,0.8)]"></div>
                <div className="w-2.5 h-2.5 bg-purple-400 rounded-full animate-bounce shadow-[0_0_8px_rgba(192,132,252,0.8)]" style={{ animationDelay: '0.15s' }}></div>
                <div className="w-2.5 h-2.5 bg-pink-400 rounded-full animate-bounce shadow-[0_0_8px_rgba(244,114,182,0.8)]" style={{ animationDelay: '0.3s' }}></div>
              </div>
            </div>
          </div>
        )}
      </div>

      {/* Input */}
      <div className="p-6 bg-gradient-to-t from-black/80 to-transparent backdrop-blur-md">
        <form onSubmit={handleSend} className="relative max-w-4xl mx-auto flex gap-3 items-end">
          <div className="relative flex-1 group">
            <div className="absolute -inset-0.5 bg-gradient-to-r from-indigo-500 via-purple-500 to-pink-500 rounded-3xl opacity-30 group-focus-within:opacity-100 blur transition duration-500 group-hover:opacity-70"></div>
            <textarea
              value={input}
              onChange={(e) => setInput(e.target.value)}
              disabled={isThinking}
              onKeyDown={(e) => {
                if (e.key === 'Enter' && !e.shiftKey) {
                  e.preventDefault();
                  handleSend(e);
                }
              }}
              rows={Math.min(4, Math.max(1, input.split('\n').length))}
              placeholder="Ask a question from your textbook... (Shift+Enter for new line)"
              className="relative w-full bg-black/60 backdrop-blur-xl rounded-3xl px-6 py-4 text-[15px] text-white placeholder-gray-500 focus:outline-none resize-none border border-white/10 leading-relaxed shadow-inner"
            />
          </div>
          <button
            type="submit"
            disabled={isThinking || !input.trim()}
            className="relative h-[56px] w-[56px] shrink-0 bg-gradient-to-br from-indigo-600 to-purple-600 rounded-2xl flex items-center justify-center text-white hover:from-indigo-500 hover:to-purple-500 transition-all disabled:opacity-50 disabled:grayscale shadow-[0_4px_20px_rgba(99,102,241,0.4)] group overflow-hidden"
          >
            <div className="absolute inset-0 bg-white/20 translate-y-full group-hover:translate-y-0 transition-transform duration-300"></div>
            <Send size={22} className="relative z-10 ml-1 group-hover:scale-110 transition-transform" />
          </button>
        </form>
      </div>
    </div>
  );
}
