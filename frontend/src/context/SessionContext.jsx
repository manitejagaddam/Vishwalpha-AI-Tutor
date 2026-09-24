import React, { createContext, useContext, useState, useEffect, useCallback, useRef } from 'react';
import { useAuth } from './AuthContext';
import { studentApi, chatApi, spacesApi } from '../api/client';
import client from '../api/client';

const SessionContext = createContext();

export const SessionProvider = ({ children }) => {
  const { student } = useAuth();
  const [sessionId, setSessionId] = useState('');
  const [subject, setSubject] = useState('Science');
  const [tutorMode, setTutorMode] = useState('standard');
  const [showContext, setShowContext] = useState(true);
  
  // Addon states
  const [studySpaces, setStudySpaces] = useState([]);
  const [activeSpaceId, setActiveSpaceId] = useState(null); // null means "All Chats"
  const [isIncognito, setIsIncognito] = useState(false);
  const [searchQuery, setSearchQuery] = useState('');
  
  const [messages, setMessages] = useState([]);
  const [sessions, setSessions] = useState([]);
  const [memory, setMemory] = useState('');
  const [metrics, setMetrics] = useState({});
  const [cognitiveSkills, setCognitiveSkills] = useState({});
  const [sessionRemark, setSessionRemark] = useState('');
  
  const [metricsAdjustments, setMetricsAdjustments] = useState(null);

  const activeSpace = studySpaces.find(s => s.id === activeSpaceId) || null;

  const refreshProfile = useCallback(async () => {
    if (!student) return;
    try {
      const data = await studentApi.getProfile(subject);
      setMetrics(data.metrics);
      setCognitiveSkills(data.cognitive_skills);
    } catch (e) {
      console.error(e);
    }
  }, [student, subject]);

  const refreshSpaces = useCallback(async () => {
    if (!student) return;
    try {
      const spaces = await spacesApi.getSpaces(subject);
      setStudySpaces(spaces || []);
    } catch (e) {
      console.error(e);
    }
  }, [student, subject]);

  const refreshSessions = useCallback(async () => {
    if (!student) return;
    try {
      const sess = await studentApi.getSessions(subject, activeSpaceId);
      setSessions(sess);
    } catch (e) {
      console.error(e);
    }
  }, [student, subject, activeSpaceId]);

  const refreshMemory = useCallback(async () => {
    if (!student) return;
    try {
      const mem = await studentApi.getMemory(subject);
      setMemory(mem);
    } catch (e) {
      console.error(e);
    }
  }, [student, subject]);

  const loadSession = useCallback(async (sid) => {
    setSessionId(sid);
    setMetricsAdjustments(null);
    try {
      if (sid) {
        const hist = await chatApi.getHistory(sid);
        setMessages(hist.recent_messages || []);
        if (hist.metrics && Object.keys(hist.metrics).length > 0) {
          setMetrics(hist.metrics);
        }
        if (hist.cognitive_skills && Object.keys(hist.cognitive_skills).length > 0) {
          setCognitiveSkills(hist.cognitive_skills);
        }
        
        const remark = await studentApi.getSessionRemark(sid);
        setSessionRemark(remark);
      } else {
        setMessages([]);
        setSessionRemark('');
      }
    } catch (e) {
      console.error(e);
    }
  }, []);

  const activateBranch = useCallback(async (messageId) => {
    if (!sessionId || !messageId) return;
    try {
      await chatApi.activateBranch(sessionId, messageId);
      // Reload session history to pick up the updated active branch path
      await loadSession(sessionId);
    } catch (e) {
      console.error('Failed to activate branch:', e);
    }
  }, [sessionId, loadSession]);

  /**
   * endSession — fire-and-forget POST /chat/session/end.
   * Call whenever the user:
   *   - switches to a different conversation
   *   - clicks "New Chat"
   *   - closes / navigates away from the app
   * The backend runs the Deep Session Sync (memory, insights, tasks, LLM metrics)
   * in a background thread so the UI is never blocked.
   */
  const endSession = useCallback((overrideSessionId, overrideSubjectId) => {
    const sid = overrideSessionId || sessionId;
    const subj = overrideSubjectId !== undefined ? overrideSubjectId : null;
    if (!sid || !student) return;
    // Extract numeric subject_id if subject is a string name
    const payload = { conversation_id: sid };
    if (subj !== null) payload.subject_id = subj;
    // Fire-and-forget — we don't await so it never blocks UI
    client.post('/chat/session/end', payload).catch(() => {});
  }, [sessionId, student]);


  // Initial load when student logs in — runs once on mount/login.
  // Subject/space changes trigger individual refreshes via their own hooks below.
  useEffect(() => {
    if (student) {
      refreshProfile();
      refreshSessions();
      refreshSpaces();
      refreshMemory();
    }
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [student?.id ?? student]);  // only re-run on login/logout, not on every callback identity change

  // Re-fetch subject-scoped data whenever subject changes
  useEffect(() => {
    if (student) {
      refreshProfile();
      refreshSessions();
      refreshSpaces();
      refreshMemory();
    }
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [subject]);

  // Re-fetch sessions when active space filter changes
  useEffect(() => {
    if (student) refreshSessions();
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [activeSpaceId]);

  return (
    <SessionContext.Provider value={{
      sessionId, setSessionId,
      subject, setSubject,
      tutorMode, setTutorMode,
      showContext, setShowContext,
      messages, setMessages,
      sessions, refreshSessions,
      studySpaces, setStudySpaces,
      activeSpaceId, setActiveSpaceId,
      activeSpace, refreshSpaces,
      isIncognito, setIsIncognito,
      searchQuery, setSearchQuery,
      activateBranch,
      memory, refreshMemory,
      metrics, setMetrics,
      cognitiveSkills, setCognitiveSkills,
      refreshProfile,
      sessionRemark, setSessionRemark,
      metricsAdjustments, setMetricsAdjustments,
      loadSession,
      endSession,
    }}>
      {children}
    </SessionContext.Provider>
  );
};

export const useSession = () => useContext(SessionContext);
