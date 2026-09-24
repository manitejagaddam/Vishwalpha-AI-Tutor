import React, { useState, useEffect, useRef } from 'react';
import { Group as PanelGroup, Panel, Separator as PanelResizeHandle } from 'react-resizable-panels';
import { useSession } from '../context/SessionContext';
import Sidebar from '../components/Sidebar/Sidebar';
import ChatArea from '../components/Chat/ChatArea';
import ContextPanel from '../components/ContextPanel/ContextPanel';

// Synchronously purge all legacy/corrupted panel layouts from localStorage
if (typeof window !== 'undefined') {
  try {
    Object.keys(localStorage).forEach(key => {
      if (key.includes('resizable') || key.includes('vishwalpha-')) {
        localStorage.removeItem(key);
      }
    });
  } catch (_) {}
}

export default function ChatPage() {
  const { showContext, subject, sessionId, endSession } = useSession();

  // Track previous sessionId so we can end the correct session on switch
  const prevSessionIdRef = useRef(sessionId);

  // Lifted quiz state — shared between Sidebar button and ChatArea
  const [activeQuiz, setActiveQuiz] = useState(null);

  // ── Purge corrupted layouts on mount (deduplicates the module-scope effect above) ──
  // Intentionally kept here too so it still fires correctly in strict mode / hot reload.
  useEffect(() => {
    try {
      Object.keys(localStorage).forEach(key => {
        if (key.includes('resizable') || key.includes('vishwalpha-')) {
          localStorage.removeItem(key);
        }
      });
    } catch (_) {}
  }, []);

  // ── Trigger session/end on app close / tab close ───────────────────────────
  useEffect(() => {
    const handleUnload = () => {
      // Use the ref so we always have the latest sessionId even during teardown
      if (prevSessionIdRef.current) {
        endSession(prevSessionIdRef.current);
      }
    };
    window.addEventListener('pagehide', handleUnload);   // mobile + bfcache
    window.addEventListener('beforeunload', handleUnload); // desktop
    return () => {
      window.removeEventListener('pagehide', handleUnload);
      window.removeEventListener('beforeunload', handleUnload);
    };
  }, [endSession]);

  // ── Trigger session/end when switching conversations ───────────────────────
  useEffect(() => {
    const prev = prevSessionIdRef.current;
    if (prev && prev !== sessionId) {
      // End the previous conversation session before switching
      endSession(prev);
    }
    prevSessionIdRef.current = sessionId;
  }, [sessionId, endSession]);

  const handleStartQuiz = ({ topic, subject: sub, source = 'manual' }) => {
    setActiveQuiz({
      topic: topic || '',
      subject: sub || subject,
      source: source || (topic ? 'mid_concept' : 'manual'),
      sessionId: sessionId || '',
      key: Date.now(),
    });
  };

  const handleQuizClose = () => setActiveQuiz(null);

  // ── New Chat: end current session before clearing ──────────────────────────
  const handleNewChat = () => {
    if (sessionId) endSession(sessionId);
  };

  return (
    <div className="flex h-screen w-screen overflow-hidden bg-transparent">
      {/* 
        Exact 1 : 3 : 2 Layout Ratio:
        - Left Sidebar (1 part)  = 16.67%
        - Center Chat  (3 parts) = 50.00% (auto remaining: 100 - 16.67 - 33.33 = 50.00%)
        - Right Context (2 parts)= 33.33%
      */}
      <PanelGroup orientation="horizontal">
        
        {/* Left Sidebar Panel (Ratio: 1 part ≈ 17%) */}
        <Panel defaultSize={222} minSize={12} maxSize={3000}>
          <Sidebar onStartQuiz={handleStartQuiz} onNewChat={handleNewChat} />
        </Panel>

        <PanelResizeHandle className="w-1.5 bg-black/20 hover:bg-indigo-500/50 transition-colors duration-200 cursor-col-resize flex flex-col justify-center items-center group relative z-10">
          <div className="h-8 w-1 rounded-full bg-white/20 group-hover:bg-indigo-300 transition-colors" />
        </PanelResizeHandle>

        {/* Center Chat Panel (Ratio: 3 parts = 50.00% auto) */}
        <Panel minSize={30}>
          <ChatArea
            activeQuiz={activeQuiz}
            onStartQuiz={handleStartQuiz}
            onQuizClose={handleQuizClose}
          />
        </Panel>

        {/* Right Context Panel (Ratio: 2 parts = 33.33%) */}
        {showContext && (
          <>
            <PanelResizeHandle className="w-1.5 bg-black/20 hover:bg-indigo-500/50 transition-colors duration-200 cursor-col-resize flex flex-col justify-center items-center group relative z-10">
              <div className="h-8 w-1 rounded-full bg-white/20 group-hover:bg-indigo-300 transition-colors" />
            </PanelResizeHandle>
            <Panel defaultSize={331} minSize={20} maxSize={5000}>
              <ContextPanel />
            </Panel>
          </>
        )}
        
      </PanelGroup>
    </div>
  );
}
