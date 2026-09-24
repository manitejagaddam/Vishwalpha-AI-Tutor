import React, { useState, useEffect, useRef } from 'react';
import { useAuth } from '../../context/AuthContext';
import { useSession } from '../../context/SessionContext';
import { useSync } from '../../context/SyncContext';
import { chatApi, quizApi, attachmentsApi, API_BASE } from '../../api/client';
import { 
  Send, Sparkles, Share2, Copy, Check, RotateCcw, 
  Edit3, EyeOff, Eye, ThumbsUp, ThumbsDown, ShieldAlert, Folder, PanelRight,
  Paperclip, X, Image as ImageIcon, FileText, Loader2, Maximize2
} from 'lucide-react';
import ReactMarkdown from 'react-markdown';
import remarkGfm from 'remark-gfm';

import QuizCard from '../Quiz/QuizCard';
import QuizSuggestionCard from '../Quiz/QuizSuggestionCard';
import YesterdayContextBanner from '../Quiz/YesterdayContextBanner';
import BranchSelector from './BranchSelector';
import ShareModal from './ShareModal';

export default function ChatArea({ activeQuiz, onStartQuiz, onQuizClose }) {
  const { student } = useAuth();
  const {
    sessionId, setSessionId,
    messages, setMessages,
    subject, tutorMode,
    showContext, setShowContext,
    activeSpace, activeSpaceId,
    isIncognito, setIsIncognito,
    refreshSessions, refreshProfile, refreshMemory,
    setMetrics, setCognitiveSkills,
    setMetricsAdjustments, setSessionRemark,
    loadSession
  } = useSession();

  const { isConnected, activeDevices, remoteTyping } = useSync();

  const [input, setInput] = useState('');
  const [isThinking, setIsThinking] = useState(false);
  const scrollRef = useRef(null);
  const fileInputRef = useRef(null);

  // ── Attachments State (Addon #3) ───────────────────────────────────────────
  const [pendingAttachments, setPendingAttachments] = useState([]);
  const [isUploading, setIsUploading] = useState(false);
  const [uploadError, setUploadError] = useState(null);
  const [previewImage, setPreviewImage] = useState(null);

  // ── Modals & Addon States ──────────────────────────────────────────────────
  const [showShareModal, setShowShareModal] = useState(false);
  const [editingMsgIndex, setEditingMsgIndex] = useState(null);
  const [editText, setEditText] = useState('');
  const [copiedMsgId, setCopiedMsgId] = useState(null);
  const [messageFeedback, setMessageFeedback] = useState({});

  // ── Quiz state ──────────────────────────────────────────────────────────────
  const [yesterdayCtx, setYesterdayCtx] = useState(null);
  const [yesterdayBannerDismissed, setYesterdayBannerDismissed] = useState(false);

  // Per-message quiz suggestions: { [msgIndex]: { topic, subject, numQuestions } }
  const [quizSuggestions, setQuizSuggestions] = useState({});
  const [dismissedSuggestions, setDismissedSuggestions] = useState(new Set());
  const quizCardRef = useRef(null);

  // Auto-scroll on new messages
  useEffect(() => {
    if (scrollRef.current && !activeQuiz) {
      scrollRef.current.scrollTop = scrollRef.current.scrollHeight;
    }
  }, [messages, isThinking]);

  // Smooth scroll directly to active quiz card
  useEffect(() => {
    if (activeQuiz) {
      const timer = setTimeout(() => {
        if (quizCardRef.current) {
          quizCardRef.current.scrollIntoView({ behavior: 'smooth', block: 'nearest' });
        }
      }, 100);
      return () => clearTimeout(timer);
    }
  }, [activeQuiz]);

  const yesterdayCtxSetRef = useRef(false);

  // ── Fetch yesterday context on mount ─────────────────────────────────────────
  useEffect(() => {
    const studentId = student?.user_id || student?.id || student?.student_id;
    if (!studentId) return;
    yesterdayCtxSetRef.current = false;
    setYesterdayCtx(null);
    setYesterdayBannerDismissed(false);

    quizApi.getYesterdayContext()  // no args — endpoint resolves student from JWT
      .then(data => {
        if (data?.topic) {
          setYesterdayCtx(data);
          yesterdayCtxSetRef.current = true;
        }
      })
      .catch(() => {});
  }, [student?.id, subject]);  // use student.id not student_id which may be undefined

  // ── Attachment handlers (Addon #3) ─────────────────────────────────────────
  const handleFileSelect = async (e) => {
    const files = Array.from(e.target.files || []);
    if (!files.length) return;
    setIsUploading(true);
    setUploadError(null);
    try {
      for (const file of files) {
        const res = await attachmentsApi.upload(file);
        setPendingAttachments(prev => [...prev, res]);
      }
    } catch (err) {
      console.error("Upload error:", err);
      setUploadError(err.response?.data?.detail || err.message || "Failed to upload file.");
    } finally {
      setIsUploading(false);
      if (fileInputRef.current) fileInputRef.current.value = '';
    }
  };

  const removeAttachment = (idxToRemove) => {
    setPendingAttachments(prev => prev.filter((_, i) => i !== idxToRemove));
  };

  // ── Core send message function (supports branching with parentMessageId) ─────
  const executeSend = async (questionText, parentMessageId = null) => {
    if (!questionText.trim() && pendingAttachments.length === 0) return;

    const finalQuestion = questionText.trim() || (pendingAttachments.length > 0 ? "Please analyze and explain the attached diagram / problem." : "");
    const currentAttachments = [...pendingAttachments];
    setPendingAttachments([]);

    // Optimistic append
    const newMsg = { 
      role: 'student', 
      content: finalQuestion,
      parent_message_id: parentMessageId,
      attachments: currentAttachments,
    };
    const clientTempId = `stream-${Date.now()}`;
    setMessages(prev => [...prev, newMsg]);
    
    // Add empty tutor message to stream into with explicit temporary client ID
    setMessages(prev => [...prev, {
      id: clientTempId,
      role: 'tutor',
      content: '',
      sources: [],
      isStreaming: true
    }]);
    
    setIsThinking(true);

    try {
      await chatApi.sendMessageStream(
        {
          session_id: sessionId,
          parent_message_id: parentMessageId,
          study_space_id: activeSpaceId,
          incognito: isIncognito,
          question: finalQuestion,
          subject: subject,
          tutor_mode: tutorMode,
          attachments: currentAttachments,
        },
        // onChunk
        (token, meta) => {
          if (meta) {
            if (!sessionId && meta.conversation_id) {
              setSessionId(meta.conversation_id);
              refreshSessions();
            }
            if (meta.is_session_start && meta.yesterday_context && !yesterdayCtxSetRef.current) {
              setYesterdayCtx(meta.yesterday_context);
              yesterdayCtxSetRef.current = true;
            }
          }
          if (token) {
            setIsThinking(false);
            setMessages(prev => {
              const idx = prev.findIndex(m => m.id === clientTempId);
              const newMsgs = [...prev];
              const targetIdx = idx !== -1 ? idx : newMsgs.length - 1;
              const last = { ...newMsgs[targetIdx] };
              last.content = (last.content || '') + token;
              newMsgs[targetIdx] = last;
              return newMsgs;
            });
          }
        },
        // onDone
        (data) => {
          setMessages(prev => {
            // Locate the streaming message by temp ID or server ID
            let targetIdx = prev.findIndex(m => m.id === clientTempId || (data.message_id && m.id === data.message_id));
            if (targetIdx === -1) targetIdx = prev.length - 1;

            const newMsgs = [...prev];
            const last = { ...newMsgs[targetIdx] };
            last.isStreaming = false;
            last.id = data.message_id || last.id;
            last.sources = data.sources || last.sources || [];
            last.chunks = data.chunks || last.chunks || [];
            last.context = data.context || last.context || '';
            last.prompt_messages = data.prompt_messages || last.prompt_messages || [];
            last.chapter = data.routed_chapter || last.chapter;
            last.topic = data.routed_topic || last.topic;
            last.question_type = data.question_type || last.question_type;
            last.quiz_suggestion = data.quiz_suggestion || last.quiz_suggestion || null;
            newMsgs[targetIdx] = last;

            // Deduplicate across array so the message ID and client ID never create two bubbles
            const seenIds = new Set();
            const deduplicated = [];
            for (const [idx, msg] of newMsgs.entries()) {
              // Use index as tiebreaker so identical-content messages are never collapsed
              const key = msg.id && msg.id !== clientTempId ? msg.id : `__idx_${idx}`;
              if (seenIds.has(key)) continue;
              seenIds.add(key);
              deduplicated.push(msg);
            }
            
            if (data.quiz_suggestion) {
              setQuizSuggestions(old => ({ ...old, [targetIdx]: data.quiz_suggestion }));
            }
            return deduplicated;
          });

          if (data.metrics) {
            setMetrics(data.metrics);
          }
          if (data.cognitive_skills) {
            setCognitiveSkills(data.cognitive_skills);
          }
          if (data.metrics_adjustments && !isIncognito) {
            setMetricsAdjustments(data.metrics_adjustments);
          }

          if (!isIncognito) {
            refreshProfile();
            refreshMemory();
          }
          setIsThinking(false);

          if (sessionId) {
            refreshSessions();
          }
        },
        // onError
        (e) => {
          setMessages(prev => {
            const newMsgs = [...prev];
            const last = { ...newMsgs[newMsgs.length - 1] };
            last.isStreaming = false;
            last.content += `\n\n⚠️ Error: ${e.message}`;
            newMsgs[newMsgs.length - 1] = last;
            return newMsgs;
          });
          setIsThinking(false);
        }
      );
    } catch (e) {
      setMessages(prev => {
        const newMsgs = [...prev];
        const last = { ...newMsgs[newMsgs.length - 1] };
        last.isStreaming = false;
        last.content += `\n\n⚠️ Catch Error: ${e.message}`;
        newMsgs[newMsgs.length - 1] = last;
        return newMsgs;
      });
      setIsThinking(false);
    }
  };

  const handleSend = (e) => {
    e.preventDefault();
    if ((!input.trim() && pendingAttachments.length === 0) || isThinking || isUploading) return;
    const text = input.trim();
    setInput('');
    executeSend(text);
  };

  // ── Branching Handlers (Edit & Regenerate) ───────────────────────────────────

  const handleStartEdit = (index, currentContent) => {
    setEditingMsgIndex(index);
    setEditText(currentContent);
  };

  const handleCancelEdit = () => {
    setEditingMsgIndex(null);
    setEditText('');
  };

  const handleSubmitEdit = (msg) => {
    if (!editText.trim()) return;
    const text = editText.trim();
    handleCancelEdit();
    // Branch off from the same parent node as the message being edited
    executeSend(text, msg.parent_message_id || null);
  };

  const handleRegenerate = (tutorMsgIndex) => {
    if (isThinking) return;
    // Find the corresponding student message (usually tutorMsgIndex - 1)
    const studentMsg = messages[tutorMsgIndex - 1];
    if (studentMsg && studentMsg.role === 'student') {
      executeSend(studentMsg.content, studentMsg.parent_message_id || null);
    }
  };

  const handleCopyMessage = (content, msgId) => {
    navigator.clipboard.writeText(content);
    setCopiedMsgId(msgId);
    setTimeout(() => setCopiedMsgId(null), 2000);
  };

  const handleFeedback = async (msgId, rating) => {
    if (!msgId) return;
    setMessageFeedback(prev => ({ ...prev, [msgId]: rating }));
    try {
      await chatApi.sendFeedback(msgId, rating);
    } catch (e) {
      console.error('Failed to submit feedback:', e);
    }
  };

  // ── Quiz handlers ──────────────────────────────────────────────────────────

  const startQuiz = ({ topic, subject: sub, source = 'manual' }) => {
    setYesterdayBannerDismissed(true);
    if (onStartQuiz) {
      onStartQuiz({ topic, subject: sub || subject, source });
    }
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
    if (onQuizClose) onQuizClose();
    refreshProfile();
    refreshMemory();
  };

  // ── Render ─────────────────────────────────────────────────────────────────

  return (
    <div className="flex flex-col h-full bg-black/20 backdrop-blur-sm relative z-0">

      {/* Top Header Bar with Workspace, Incognito, and Share controls */}
      <div className="p-4 px-6 border-b border-white/5 bg-linear-to-b from-black/70 to-transparent sticky top-0 z-10 backdrop-blur-md flex items-center justify-between">
        
        {/* Title & Workspace Badge */}
        <div className="flex items-center gap-3">
          <div className="flex items-center gap-2">
            <Sparkles className="text-indigo-400" size={20} />
            <h1 className="text-lg font-black tracking-tight bg-clip-text text-transparent bg-linear-to-r from-indigo-400 via-purple-400 to-pink-400">
              VishwAlpha AI
            </h1>
          </div>

          {activeSpace && (
            <span className="hidden sm:inline-flex items-center gap-1 px-2.5 py-0.5 rounded-full text-[11px] font-bold bg-violet-500/20 text-violet-300 border border-violet-500/30">
              <Folder size={11} /> {activeSpace.title}
            </span>
          )}
        </div>

        {/* Action Controls: Live Sync, Incognito Toggle & Share */}
        <div className="flex items-center gap-2">
          {/* Real-time Cross-Device Sync Indicator (Addon #4) */}
          <div 
            className={`flex items-center gap-1.5 px-2.5 py-1.5 rounded-xl text-xs font-semibold border transition-all ${
              isConnected 
                ? 'bg-emerald-500/10 text-emerald-400 border-emerald-500/30' 
                : 'bg-black/30 text-gray-500 border-white/5'
            }`}
            title={isConnected ? `Real-Time Sync Active (${activeDevices} device${activeDevices > 1 ? 's' : ''} connected)` : 'Connecting to Real-Time Sync...'}
          >
            <span className="relative flex h-2 w-2">
              {isConnected && (
                <span className="animate-ping absolute inline-flex h-full w-full rounded-full bg-emerald-400 opacity-75"></span>
              )}
              <span className={`relative inline-flex rounded-full h-2 w-2 ${isConnected ? 'bg-emerald-400' : 'bg-gray-600'}`}></span>
            </span>
            <span className="hidden lg:inline text-[11px] font-mono tracking-tight">{isConnected ? 'Live Sync' : 'Offline'}</span>
          </div>

          {/* Incognito Toggle Button */}
          <button
            onClick={() => setIsIncognito(!isIncognito)}
            className={`flex items-center gap-1.5 px-3 py-1.5 rounded-xl text-xs font-semibold transition-all border ${
              isIncognito
                ? 'bg-amber-500/20 text-amber-300 border-amber-500/40 shadow-[0_0_15px_rgba(245,158,11,0.25)]'
                : 'bg-black/30 text-gray-400 border-white/10 hover:bg-white/5 hover:text-gray-200'
            }`}
            title="Incognito mode skips saving cognitive memory or altering your streaks."
          >
            {isIncognito ? <EyeOff size={14} className="text-amber-400" /> : <Eye size={14} />}
            <span className="hidden md:inline">{isIncognito ? 'Incognito ON' : 'Incognito'}</span>
          </button>

          {/* Share Button */}
          <button
            onClick={() => setShowShareModal(true)}
            disabled={!sessionId || messages.length === 0}
            className="flex items-center gap-1.5 px-3 py-1.5 rounded-xl text-xs font-semibold bg-indigo-500/10 hover:bg-indigo-500/25 text-indigo-300 border border-indigo-500/30 transition-all disabled:opacity-30 disabled:cursor-not-allowed hover:scale-105 active:scale-95"
            title="Create a shareable link of this chat"
          >
            <Share2 size={13} />
            <span className="hidden sm:inline">Share</span>
          </button>

          {/* Inspector Panel Toggle Button */}
          <button
            onClick={() => setShowContext(!showContext)}
            className={`flex items-center gap-1.5 px-3 py-1.5 rounded-xl text-xs font-semibold transition-all border ${
              showContext
                ? 'bg-purple-500/20 text-purple-300 border-purple-500/40 shadow-[0_0_15px_rgba(168,85,247,0.25)]'
                : 'bg-black/30 text-gray-400 border-white/10 hover:bg-white/5 hover:text-gray-200'
            }`}
            title="Toggle Live Retrieval, Context & Cognitive Inspector"
          >
            <PanelRight size={14} className={showContext ? "text-purple-400" : ""} />
            <span className="hidden sm:inline">{showContext ? 'Inspector Open' : 'Inspector'}</span>
          </button>
        </div>
      </div>

      {/* Remote Cross-Device Activity Notice (Addon #4) */}
      {remoteTyping && (
        <div className="bg-indigo-950/40 border-b border-indigo-500/30 px-6 py-1.5 flex items-center justify-center gap-2 text-xs text-indigo-300 backdrop-blur-md animate-pulse">
          <span className="w-2 h-2 rounded-full bg-indigo-400 animate-ping"></span>
          <span>Activity detected from another connected device...</span>
        </div>
      )}

      {/* Incognito Ambient Warning Notice */}
      {isIncognito && (
        <div className="bg-amber-950/40 border-b border-amber-500/20 px-6 py-2 flex items-center justify-center gap-2 text-xs text-amber-300 backdrop-blur-md">
          <ShieldAlert size={14} className="text-amber-400 shrink-0" />
          <span>Incognito Mode Active: Chat is private and will not affect your cognitive profile, memory, or streaks.</span>
        </div>
      )}

      {/* Messages Scroll Area */}
      <div className="flex-1 overflow-y-auto p-6 space-y-5" ref={scrollRef}>

        {/* Yesterday Context Banner */}
        {yesterdayCtx && !yesterdayBannerDismissed && (
          <YesterdayContextBanner
            context={yesterdayCtx}
            onTake={handleYesterdayTake}
            onDismiss={() => setYesterdayBannerDismissed(true)}
          />
        )}


        {/* Empty state */}
        {messages.length === 0 && !yesterdayCtx && !activeQuiz && (
          <div className="flex flex-col items-center justify-center h-full text-center -mt-10">
            <div className="w-24 h-24 bg-linear-to-br from-indigo-500/20 to-purple-500/20 rounded-full flex items-center justify-center mb-6 shadow-[0_0_40px_rgba(99,102,241,0.2)] border border-indigo-500/20">
              <Sparkles className="text-indigo-400 w-10 h-10" />
            </div>
            <h2 className="text-3xl font-bold mb-3 text-white">Namaste, {student.username}!</h2>
            <p className="text-gray-400 text-lg max-w-md mx-auto leading-relaxed">
              I'm VishwAlpha. I see you're using <strong className="text-indigo-400 bg-indigo-500/10 px-2 py-0.5 rounded">{tutorMode === 'standard' ? 'Standard' : 'Deep Learning'}</strong> mode for {subject}.
            </p>
            {activeSpace && (
              <p className="text-xs text-violet-300 mt-2 font-medium bg-violet-950/40 border border-violet-500/30 px-3 py-1 rounded-full inline-block">
                Workspace: <strong>{activeSpace.title}</strong>
              </p>
            )}
            <p className="text-gray-500 mt-6 font-medium">What would you like to learn today?</p>
          </div>
        )}

        {/* Message list */}
        {messages.map((msg, i) => (
          <div key={msg.id || i} className="group relative">
            <div className={`flex ${msg.role === 'student' ? 'justify-end' : 'justify-start'}`}>
              <div className={`max-w-[85%] flex gap-4 ${msg.role === 'student' ? 'flex-row-reverse' : 'flex-row'} items-end`}>

                {/* Avatar */}
                <div className={`w-10 h-10 rounded-2xl flex items-center justify-center text-lg shrink-0 shadow-lg border border-white/10 relative z-10 ${
                  msg.role === 'student'
                    ? 'bg-gradient-to-br from-indigo-500 to-purple-600'
                    : 'bg-gradient-to-br from-teal-500 to-emerald-600'
                }`}>
                  {msg.role === 'student' ? '👤' : '🤖'}
                </div>

                {/* Bubble Container */}
                <div className="flex flex-col gap-1.5 max-w-full">
                  <div className={`p-5 text-[15px] leading-relaxed shadow-xl relative ${
                    msg.role === 'student'
                      ? 'bg-gradient-to-br from-indigo-600 to-purple-700 text-white rounded-3xl rounded-br-sm shadow-[0_4px_20px_rgba(99,102,241,0.3)]'
                      : 'glass-card text-gray-100 rounded-3xl rounded-bl-sm border-white/5'
                  }`}>

                    {/* Mode tag for tutor responses */}
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

                    {/* Attached images / diagrams (Addon #3) */}
                    {msg.attachments && msg.attachments.length > 0 && (
                      <div className="flex flex-wrap gap-2.5 mb-3">
                        {msg.attachments.map((att, attIdx) => {
                          const isImg = att.content_type?.startsWith('image/') || att.url?.match(/\.(png|jpe?g|webp|gif)$/i);
                          const fullUrl = att.url?.startsWith('http') ? att.url : `${API_BASE}${att.url}`;
                          return (
                            <div 
                              key={attIdx} 
                              onClick={() => isImg && setPreviewImage(fullUrl)}
                              className={`group relative flex items-center gap-2.5 p-2 pr-3.5 rounded-2xl bg-white/10 hover:bg-white/15 border border-white/10 transition-all shadow-md ${isImg ? 'cursor-pointer hover:border-indigo-400/50' : ''}`}
                            >
                              {isImg ? (
                                <img 
                                  src={att.base64_thumbnail || fullUrl} 
                                  alt={att.filename} 
                                  className="w-12 h-12 object-cover rounded-xl border border-white/10 group-hover:scale-105 transition-transform" 
                                />
                              ) : (
                                <div className="w-12 h-12 rounded-xl bg-indigo-500/20 flex items-center justify-center text-indigo-300">
                                  <FileText size={22} />
                                </div>
                              )}
                              <div className="flex flex-col text-left">
                                <span className="text-xs font-semibold text-white max-w-[150px] truncate">{att.filename}</span>
                                <span className="text-[10px] text-gray-400 max-w-[150px] truncate">
                                  {att.topic_hint || (isImg ? 'Multimodal Diagram' : 'Document')}
                                </span>
                                {att.description && (
                                  <span className="text-[10px] text-indigo-300 max-w-[150px] truncate">
                                    Vision Analyzed
                                  </span>
                                )}
                              </div>
                              {isImg && (
                                <Maximize2 size={13} className="text-gray-400 group-hover:text-white opacity-0 group-hover:opacity-100 transition-opacity ml-1" />
                              )}
                            </div>
                          );
                        })}
                      </div>
                    )}

                    {/* Inline Editor (if currently editing this student message) */}
                    {editingMsgIndex === i ? (
                      <div className="space-y-3 min-w-[280px] sm:min-w-[400px]">
                        <textarea
                          value={editText}
                          onChange={(e) => setEditText(e.target.value)}
                          rows={3}
                          className="w-full bg-black/50 border border-white/20 rounded-2xl p-3 text-sm text-white focus:outline-none focus:ring-2 focus:ring-white/40 resize-none leading-relaxed"
                        />
                        <div className="flex justify-end gap-2">
                          <button
                            onClick={handleCancelEdit}
                            className="px-3 py-1.5 rounded-xl text-xs font-semibold text-gray-300 hover:bg-white/10 transition-colors"
                          >
                            Cancel
                          </button>
                          <button
                            onClick={() => handleSubmitEdit(msg)}
                            disabled={!editText.trim()}
                            className="px-4 py-1.5 rounded-xl bg-white text-indigo-900 font-bold text-xs shadow-md transition-all hover:bg-gray-100 disabled:opacity-50"
                          >
                            Save & Branch
                          </button>
                        </div>
                      </div>
                    ) : (
                      /* Content: stream as plain text during generation, render Markdown when done */
                      <div className={`markdown-content [&_h1]:text-2xl [&_h1]:font-bold [&_h1]:mb-3 [&_h2]:text-xl [&_h2]:font-bold [&_h2]:mt-5 [&_h2]:mb-2 [&_h3]:text-lg [&_h3]:font-semibold [&_p]:mb-3 [&_ul]:list-disc [&_ul]:pl-5 [&_ul]:mb-3 [&_ol]:list-decimal [&_ol]:pl-5 [&_ol]:mb-3 [&_li]:mb-1 [&_table]:w-full [&_table]:border-collapse [&_table]:mb-4 [&_table]:text-sm [&_th]:border [&_th]:border-white/20 [&_th]:p-2 [&_th]:bg-white/10 [&_td]:border [&_td]:border-white/10 [&_td]:p-2 [&_blockquote]:border-l-4 [&_blockquote]:border-indigo-400 [&_blockquote]:pl-4 [&_blockquote]:italic [&_blockquote]:text-gray-300 [&_strong]:font-bold [&_code]:bg-black/30 [&_code]:px-1.5 [&_code]:py-0.5 [&_code]:rounded text-[15px] leading-relaxed ${
                        msg.role === 'student' ? '[&_strong]:text-white' : '[&_strong]:text-indigo-200'
                      }`}>
                        {msg.isStreaming ? (
                          /* Raw text during streaming — avoids ReactMarkdown re-parsing every token */
                          <span style={{ whiteSpace: 'pre-wrap' }}>{msg.content}</span>
                        ) : (
                          <ReactMarkdown remarkPlugins={[remarkGfm]}>
                            {msg.content}
                          </ReactMarkdown>
                        )}
                      </div>
                    )}

                    {/* Sources citations */}
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

                  {/* Message Action Bar (Branch Selector, Edit, Regenerate, Copy, Feedback) */}
                  <div className={`flex items-center gap-2 px-1 text-xs text-gray-400 opacity-60 hover:opacity-100 transition-opacity ${
                    msg.role === 'student' ? 'justify-end' : 'justify-start'
                  }`}>
                    
                    {/* Sibling Branch Selector (◀ 1/3 ▶) */}
                    <BranchSelector 
                      siblingIds={msg.sibling_ids}
                      siblingIndex={msg.sibling_index || 0}
                      siblingCount={msg.sibling_count || 1}
                    />

                    {/* Student Edit Button */}
                    {msg.role === 'student' && editingMsgIndex !== i && (
                      <button
                        onClick={() => handleStartEdit(i, msg.content)}
                        className="p-1 rounded-lg hover:bg-white/10 hover:text-white transition-colors flex items-center gap-1"
                        title="Edit question and create a branch"
                      >
                        <Edit3 size={12} />
                        <span className="text-[10px]">Edit</span>
                      </button>
                    )}

                    {/* Tutor Regenerate Button */}
                    {msg.role === 'tutor' && !msg.isStreaming && (
                      <button
                        onClick={() => handleRegenerate(i)}
                        disabled={isThinking}
                        className="p-1 rounded-lg hover:bg-white/10 hover:text-white transition-colors flex items-center gap-1 disabled:opacity-30"
                        title="Regenerate this response"
                      >
                        <RotateCcw size={12} />
                        <span className="text-[10px]">Regenerate</span>
                      </button>
                    )}

                    {/* Copy Button */}
                    <button
                      onClick={() => handleCopyMessage(msg.content, msg.id || i)}
                      className="p-1 rounded-lg hover:bg-white/10 hover:text-white transition-colors"
                      title="Copy text"
                    >
                      {copiedMsgId === (msg.id || i) ? (
                        <Check size={12} className="text-emerald-400" />
                      ) : (
                        <Copy size={12} />
                      )}
                    </button>

                    {/* Tutor Thumbs Feedback */}
                    {msg.role === 'tutor' && msg.id && (
                      <div className="flex items-center gap-1 border-l border-white/10 pl-1.5 ml-1">
                        <button
                          onClick={() => handleFeedback(msg.id, 1)}
                          className={`p-1 rounded-lg hover:bg-white/10 transition-colors ${
                            messageFeedback[msg.id] === 1 ? 'text-emerald-400' : 'hover:text-emerald-400'
                          }`}
                          title="Helpful response"
                        >
                          <ThumbsUp size={12} />
                        </button>
                        <button
                          onClick={() => handleFeedback(msg.id, -1)}
                          className={`p-1 rounded-lg hover:bg-white/10 transition-colors ${
                            messageFeedback[msg.id] === -1 ? 'text-rose-400' : 'hover:text-rose-400'
                          }`}
                          title="Not helpful"
                        >
                          <ThumbsDown size={12} />
                        </button>
                      </div>
                    )}
                  </div>

                </div>
              </div>
            </div>

            {/* Quiz Suggestion Card */}
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

        {/* Active Quiz Card */}
        {activeQuiz && (
          <div ref={quizCardRef} className="w-full max-w-3xl mx-auto my-4 transition-all">
            <QuizCard
              key={activeQuiz.key || 'active-quiz'}
              topic={activeQuiz.topic}
              subject={activeQuiz.subject}
              source={activeQuiz.source}
              sessionId={activeQuiz.sessionId}
              numQuestions={7}
              onClose={handleQuizClose}
            />
          </div>
        )}

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

      {/* Input area */}
      <div className="p-6 bg-gradient-to-t from-black/80 to-transparent backdrop-blur-md">
        {/* Uploaded attachments preview row (Addon #3) */}
        {(pendingAttachments.length > 0 || isUploading || uploadError) && (
          <div className="max-w-4xl mx-auto mb-2.5 flex flex-wrap gap-2 items-center px-1">
            {pendingAttachments.map((att, idx) => (
              <div key={idx} className="flex items-center gap-2 px-3 py-1.5 rounded-full bg-white/10 border border-white/20 backdrop-blur-md text-xs text-white shadow-lg animate-fadeIn">
                <ImageIcon size={14} className="text-indigo-400" />
                <span className="max-w-[140px] truncate font-medium">{att.filename}</span>
                <button
                  type="button"
                  onClick={() => removeAttachment(idx)}
                  className="p-0.5 rounded-full hover:bg-white/20 text-gray-400 hover:text-white transition-colors"
                  title="Remove attachment"
                >
                  <X size={13} />
                </button>
              </div>
            ))}
            {isUploading && (
              <div className="flex items-center gap-2 px-3.5 py-1.5 rounded-full bg-indigo-500/20 border border-indigo-400/30 text-xs text-indigo-200 backdrop-blur-md animate-pulse">
                <Loader2 size={13} className="animate-spin text-indigo-400" />
                <span>Analyzing diagram / homework with Vision...</span>
              </div>
            )}
            {uploadError && (
              <div className="flex items-center gap-1.5 px-3 py-1.5 rounded-full bg-rose-500/20 border border-rose-500/30 text-xs text-rose-300">
                <span>{uploadError}</span>
                <button type="button" onClick={() => setUploadError(null)} className="ml-1 hover:text-white">
                  <X size={12} />
                </button>
              </div>
            )}
          </div>
        )}

        <form onSubmit={handleSend} className="relative max-w-4xl mx-auto flex gap-3 items-end">
          {/* File input for student attachments */}
          <input
            type="file"
            ref={fileInputRef}
            onChange={handleFileSelect}
            accept="image/*,application/pdf"
            multiple
            className="hidden"
            id="chat-file-upload"
          />
          <label
            htmlFor="chat-file-upload"
            className={`relative h-[56px] w-[50px] shrink-0 bg-white/5 hover:bg-white/10 border border-white/10 hover:border-white/20 rounded-2xl flex items-center justify-center cursor-pointer transition-all text-gray-400 hover:text-white shadow-inner ${
              isUploading ? 'opacity-50 pointer-events-none' : ''
            } ${pendingAttachments.length > 0 ? 'text-indigo-400 border-indigo-400/40 bg-indigo-500/10' : ''}`}
            title="Attach diagram, math problem, or homework photo"
          >
            <Paperclip size={20} />
          </label>

          <div className="relative flex-1 group">
            <div className="absolute -inset-0.5 bg-gradient-to-r from-indigo-500 via-purple-500 to-pink-500 rounded-3xl opacity-30 group-focus-within:opacity-100 blur transition duration-500 group-hover:opacity-70"></div>
            <textarea
              value={input}
              onChange={(e) => setInput(e.target.value)}
              disabled={isThinking || isUploading}
              onKeyDown={(e) => {
                if (e.key === 'Enter' && !e.shiftKey) {
                  e.preventDefault();
                  handleSend(e);
                }
              }}
              rows={Math.min(4, Math.max(1, input.split('\n').length))}
              placeholder={
                isIncognito 
                  ? "Incognito: Ask a question (no memory saved)..."
                  : activeSpace 
                    ? `Ask within ${activeSpace.title}... (Shift+Enter for new line)`
                    : "Ask a question or upload a diagram... (Shift+Enter for new line)"
              }
              className="relative w-full bg-black/60 backdrop-blur-xl rounded-3xl px-6 py-4 text-[15px] text-white placeholder-gray-500 focus:outline-none resize-none border border-white/10 leading-relaxed shadow-inner"
            />
          </div>
          <button
            type="submit"
            disabled={isThinking || isUploading || (!input.trim() && pendingAttachments.length === 0)}
            className="relative h-[56px] w-[56px] shrink-0 bg-gradient-to-br from-indigo-600 to-purple-600 rounded-2xl flex items-center justify-center text-white hover:from-indigo-500 hover:to-purple-500 transition-all disabled:opacity-50 disabled:grayscale shadow-[0_4px_20px_rgba(99,102,241,0.4)] group overflow-hidden"
          >
            <div className="absolute inset-0 bg-white/20 translate-y-full group-hover:translate-y-0 transition-transform duration-300"></div>
            <Send size={22} className="relative z-10 ml-1 group-hover:scale-110 transition-transform" />
          </button>
        </form>
      </div>

      {/* Image Lightbox Modal */}
      {previewImage && (
        <div 
          onClick={() => setPreviewImage(null)}
          className="fixed inset-0 z-50 bg-black/85 backdrop-blur-md flex items-center justify-center p-4 cursor-zoom-out"
        >
          <div className="relative max-w-4xl max-h-[90vh] overflow-hidden rounded-2xl border border-white/20 shadow-2xl">
            <img 
              src={previewImage} 
              alt="Attachment Preview" 
              className="w-full h-full object-contain max-h-[85vh] rounded-2xl" 
            />
            <button 
              onClick={() => setPreviewImage(null)}
              className="absolute top-3 right-3 p-2 rounded-full bg-black/60 hover:bg-black text-white transition-colors"
            >
              <X size={18} />
            </button>
          </div>
        </div>
      )}

      {/* Share Modal */}
      {showShareModal && (
        <ShareModal
          sessionId={sessionId}
          onClose={() => setShowShareModal(false)}
        />
      )}

    </div>
  );
}
