import React, { useState, useEffect, useRef } from 'react';
import { useAuth } from '../../context/AuthContext';
import { useSession } from '../../context/SessionContext';
import { chatApi } from '../../api/client';
import { Send } from 'lucide-react';

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

  useEffect(() => {
    if (scrollRef.current) {
      scrollRef.current.scrollTop = scrollRef.current.scrollHeight;
    }
  }, [messages, isThinking]);

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
      
      // If it's a new session, backend will return a new session_id
      if (!sessionId && response.session_id) {
        setSessionId(response.session_id);
        refreshSessions();
      }
      
      // Update UI with response
      const tutorMsg = {
        role: 'tutor',
        content: response.answer,
        sources: response.sources,
        chapter: response.routed_chapter,
        topic: response.routed_topic,
        question_type: response.question_type,
        chunks: response.raw_chunks,
        prompt_messages: response.prompt_messages
      };
      
      setMessages(prev => [...prev, tutorMsg]);
      
      if (response.metrics_adjustments) {
        setMetricsAdjustments(response.metrics_adjustments);
      }
      
      // Refresh context data if turn modulo hits (handled in backend mostly, but we can optimistically pull)
      refreshProfile();
      refreshMemory();
      
    } catch (e) {
      setMessages(prev => [...prev, { role: 'tutor', content: `⚠️ Error: ${e.response?.data?.detail || e.message}` }]);
    } finally {
      setIsThinking(false);
    }
  };

  return (
    <div className="flex flex-col h-full bg-gray-900/50">
      {/* Header */}
      <div className="p-4 text-center border-b border-white/5 bg-white/5">
        <h1 className="text-xl font-bold bg-clip-text text-transparent bg-gradient-to-r from-indigo-400 to-purple-400">VishwAlpha AI Tutor</h1>
        <p className="text-xs text-gray-400">Personalised NCERT curriculum assistant</p>
      </div>
      
      {/* Messages */}
      <div className="flex-1 overflow-y-auto p-4 space-y-6" ref={scrollRef}>
        {messages.length === 0 && (
          <div className="text-center text-gray-500 mt-20">
            <p className="mb-2">Namaste! I'm VishwAlpha, your NCERT AI Tutor.</p>
            <p>I see you're using <strong className="text-indigo-400">{tutorMode === 'standard' ? 'Standard' : 'Deep Learning (Socratic)'}</strong> mode.</p>
            <p className="mt-4">What would you like to learn today?</p>
          </div>
        )}
        
        {messages.map((msg, i) => (
          <div key={i} className={`flex ${msg.role === 'student' ? 'justify-end' : 'justify-start'}`}>
            <div className={`max-w-[80%] flex gap-3 ${msg.role === 'student' ? 'flex-row-reverse' : 'flex-row'}`}>
              
              <div className={`w-8 h-8 rounded-full flex items-center justify-center text-sm shrink-0 ${
                msg.role === 'student' ? 'bg-gradient-to-br from-indigo-500 to-purple-600' : 'bg-gradient-to-br from-teal-500 to-emerald-500'
              }`}>
                {msg.role === 'student' ? '👤' : '🤖'}
              </div>
              
              <div className={`p-4 rounded-2xl text-sm leading-relaxed ${
                msg.role === 'student' 
                  ? 'bg-gradient-to-br from-indigo-600 to-purple-700 text-white rounded-tr-sm' 
                  : 'bg-white/10 border border-white/10 text-gray-200 rounded-tl-sm'
              }`}>
                
                {msg.role === 'tutor' && (
                  <div className="mb-2">
                    <span className={`text-[10px] font-bold px-2 py-0.5 rounded-full ${
                      msg.question_type === 'conversational' ? 'bg-emerald-500/20 text-emerald-400' : 'bg-indigo-500/20 text-indigo-400'
                    }`}>
                      {msg.question_type === 'conversational' ? '💬 Conversational' : '📚 Curriculum'}
                    </span>
                  </div>
                )}
                
                <div className="whitespace-pre-wrap">{msg.content}</div>
                
                {msg.sources && msg.sources.length > 0 && (
                  <div className="mt-3 flex flex-wrap gap-2">
                    {msg.sources.map((s, idx) => (
                      <span key={idx} className="bg-white/5 border border-white/10 text-gray-400 text-[10px] px-2 py-1 rounded">
                        📚 {s.topic} ({(s.score).toFixed(2)})
                      </span>
                    ))}
                  </div>
                )}
              </div>
              
            </div>
          </div>
        ))}
        
        {isThinking && (
          <div className="flex justify-start">
            <div className="flex gap-3 max-w-[80%]">
              <div className="w-8 h-8 rounded-full bg-gradient-to-br from-teal-500 to-emerald-500 flex items-center justify-center text-sm">🤖</div>
              <div className="p-4 rounded-2xl rounded-tl-sm bg-white/10 border border-white/10 text-gray-200 flex gap-1 items-center h-[52px]">
                <div className="w-2 h-2 bg-gray-400 rounded-full animate-bounce"></div>
                <div className="w-2 h-2 bg-gray-400 rounded-full animate-bounce" style={{ animationDelay: '0.2s' }}></div>
                <div className="w-2 h-2 bg-gray-400 rounded-full animate-bounce" style={{ animationDelay: '0.4s' }}></div>
              </div>
            </div>
          </div>
        )}
      </div>
      
      {/* Input */}
      <div className="p-4 bg-white/5 border-t border-white/10">
        <form onSubmit={handleSend} className="relative max-w-4xl mx-auto flex gap-2">
          <input
            type="text"
            value={input}
            onChange={(e) => setInput(e.target.value)}
            disabled={isThinking}
            placeholder="Ask a question from your textbook... (e.g. What is rancidity?)"
            className="flex-1 bg-white/10 border border-white/20 rounded-full px-6 py-3 text-sm text-white focus:outline-none focus:border-indigo-500 transition-colors disabled:opacity-50"
          />
          <button 
            type="submit" 
            disabled={isThinking || !input.trim()}
            className="w-12 h-12 bg-indigo-600 rounded-full flex items-center justify-center text-white hover:bg-indigo-700 transition-colors disabled:opacity-50 disabled:hover:bg-indigo-600"
          >
            <Send size={18} className="ml-1" />
          </button>
        </form>
      </div>
    </div>
  );
}
