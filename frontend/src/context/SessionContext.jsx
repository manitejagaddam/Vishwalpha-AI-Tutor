import React, { createContext, useContext, useState, useEffect, useCallback } from 'react';
import { useAuth } from './AuthContext';
import { studentApi, chatApi } from '../api/client';

const SessionContext = createContext();

export const SessionProvider = ({ children }) => {
  const { student } = useAuth();
  const [sessionId, setSessionId] = useState('');
  const [subject, setSubject] = useState('Science');
  const [tutorMode, setTutorMode] = useState('standard');
  const [showContext, setShowContext] = useState(true);
  
  const [messages, setMessages] = useState([]);
  const [sessions, setSessions] = useState([]);
  const [memory, setMemory] = useState('');
  const [metrics, setMetrics] = useState({});
  const [cognitiveSkills, setCognitiveSkills] = useState({});
  const [sessionRemark, setSessionRemark] = useState('');
  
  const [metricsAdjustments, setMetricsAdjustments] = useState(null);

  const refreshProfile = useCallback(async () => {
    if (!student) return;
    try {
      const data = await studentApi.getProfile(student.student_id, subject);
      setMetrics(data.metrics);
      setCognitiveSkills(data.cognitive_skills);
    } catch (e) {
      console.error(e);
    }
  }, [student, subject]);

  const refreshSessions = useCallback(async () => {
    if (!student) return;
    try {
      const sess = await studentApi.getSessions(student.student_id, subject);
      setSessions(sess);
    } catch (e) {
      console.error(e);
    }
  }, [student, subject]);

  const refreshMemory = useCallback(async () => {
    if (!student) return;
    try {
      const mem = await studentApi.getMemory(student.student_id, subject);
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

  useEffect(() => {
    if (student) {
      refreshProfile();
      refreshSessions();
      refreshMemory();
    }
  }, [student, refreshProfile, refreshSessions, refreshMemory]);

  return (
    <SessionContext.Provider value={{
      sessionId, setSessionId,
      subject, setSubject,
      tutorMode, setTutorMode,
      showContext, setShowContext,
      messages, setMessages,
      sessions, refreshSessions,
      memory, refreshMemory,
      metrics, setMetrics,
      cognitiveSkills, setCognitiveSkills,
      refreshProfile,
      sessionRemark, setSessionRemark,
      metricsAdjustments, setMetricsAdjustments,
      loadSession
    }}>
      {children}
    </SessionContext.Provider>
  );
};

export const useSession = () => useContext(SessionContext);
