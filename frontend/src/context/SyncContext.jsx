import React, { createContext, useContext, useEffect, useState, useRef, useCallback } from 'react';
import { useAuth } from './AuthContext';
import { useSession } from './SessionContext';
import { API_BASE } from '../api/client';

const SyncContext = createContext(null);

export function SyncProvider({ children }) {
  const { student } = useAuth();
  const { 
    sessionId, 
    setMessages, 
    refreshSessions, 
    refreshProfile, 
    refreshMemory,
    loadStudySpaces,
  } = useSession();

  const [isConnected, setIsConnected] = useState(false);
  const [activeDevices, setActiveDevices] = useState(1);
  const [lastSyncTime, setLastSyncTime] = useState(null);
  const [remoteTyping, setRemoteTyping] = useState(false);

  const socketRef = useRef(null);
  const reconnectTimeoutRef = useRef(null);
  const pingIntervalRef = useRef(null);
  const retryCountRef = useRef(0);

  // Keep latest sessionId in a ref for socket message handler
  const currentSessionIdRef = useRef(sessionId);
  useEffect(() => {
    currentSessionIdRef.current = sessionId;
  }, [sessionId]);

  const connectWebSocket = useCallback(() => {
    if (!student?.access_token) return;

    // Resolve ws:// or wss:// URL from centralized API_BASE
    const wsProto = API_BASE.startsWith('https') ? 'wss:' : 'ws:';
    const host = API_BASE.replace(/^https?:\/\//, '');
    const wsUrl = `${wsProto}//${host}/sync/ws?token=${encodeURIComponent(student.access_token)}`;

    try {
      const ws = new WebSocket(wsUrl);
      socketRef.current = ws;

      ws.onopen = () => {
        setIsConnected(true);
        retryCountRef.current = 0;
        setLastSyncTime(new Date());

        // Heartbeat ping every 25 seconds
        if (pingIntervalRef.current) clearInterval(pingIntervalRef.current);
        pingIntervalRef.current = setInterval(() => {
          if (ws.readyState === WebSocket.OPEN) {
            ws.send(JSON.stringify({ type: 'ping' }));
          }
        }, 25000);
      };

      ws.onmessage = (event) => {
        try {
          const payload = JSON.parse(event.data);
          const { event: eventName, data } = payload;
          setLastSyncTime(new Date());

          if (eventName === 'connected') {
            setActiveDevices(data?.active_devices || 1);
          } else if (eventName === 'message_received') {
            // If the message is for the currently open chat session, sync it to the UI
            if (data?.session_id === currentSessionIdRef.current && data?.message) {
              setMessages((prev) => {
                const incomingId = data.message.id;
                // 1. If message already exists by ID, do not duplicate
                if (incomingId && prev.some((m) => m.id === incomingId)) {
                  return prev;
                }

                // 2. Check if active tab is currently streaming or just finished streaming this response
                const lastIdx = prev.length - 1;
                if (lastIdx >= 0) {
                  const last = prev[lastIdx];
                  if (last.role === 'tutor' || last.role === 'assistant') {
                    const isSameContent = last.content && data.message.content &&
                      (last.content.trim() === data.message.content.trim() ||
                       last.content.startsWith(data.message.content.slice(0, 40)) ||
                       data.message.content.startsWith(last.content.slice(0, 40)));

                    if (last.isStreaming || isSameContent) {
                      // Seamlessly merge incoming server ID and metadata into existing message bubble
                      const updated = [...prev];
                      updated[lastIdx] = {
                        ...last,
                        ...data.message,
                        isStreaming: false,
                        id: incomingId || last.id,
                      };
                      return updated;
                    }
                  }
                }

                // 3. Remote device / new turn: append message cleanly
                return [...prev, data.message];
              });
            }
            refreshSessions();
          } else if (eventName === 'quiz_completed') {
            refreshProfile();
            refreshMemory();
            refreshSessions();
          } else if (eventName === 'space_updated') {
            loadStudySpaces();
          } else if (eventName === 'typing') {
            setRemoteTyping(true);
            setTimeout(() => setRemoteTyping(false), 3000);
          }
        } catch (err) {
          console.debug('[RealTime Sync] Message parse error:', err);
        }
      };

      ws.onerror = (err) => {
        console.debug('[RealTime Sync] Socket error:', err);
      };

      ws.onclose = () => {
        setIsConnected(false);
        if (pingIntervalRef.current) clearInterval(pingIntervalRef.current);

        // Exponential backoff reconnection up to 15s
        const backoff = Math.min(1000 * Math.pow(1.5, retryCountRef.current), 15000);
        retryCountRef.current += 1;

        if (reconnectTimeoutRef.current) clearTimeout(reconnectTimeoutRef.current);
        reconnectTimeoutRef.current = setTimeout(() => {
          connectWebSocket();
        }, backoff);
      };
    } catch (err) {
      console.debug('[RealTime Sync] Failed to initialize WebSocket:', err);
    }
  }, [student?.access_token, refreshSessions, refreshProfile, refreshMemory, loadStudySpaces, setMessages]);

  useEffect(() => {
    if (student?.access_token) {
      connectWebSocket();
    } else {
      if (socketRef.current) socketRef.current.close();
      setIsConnected(false);
    }

    return () => {
      if (reconnectTimeoutRef.current) clearTimeout(reconnectTimeoutRef.current);
      if (pingIntervalRef.current) clearInterval(pingIntervalRef.current);
      if (socketRef.current) {
        socketRef.current.onclose = null;
        socketRef.current.close();
      }
    };
  }, [student?.access_token, connectWebSocket]);

  const sendSyncEvent = useCallback((type, data = {}) => {
    if (socketRef.current && socketRef.current.readyState === WebSocket.OPEN) {
      socketRef.current.send(JSON.stringify({ type, data }));
    }
  }, []);

  return (
    <SyncContext.Provider
      value={{
        isConnected,
        activeDevices,
        lastSyncTime,
        remoteTyping,
        sendSyncEvent,
      }}
    >
      {children}
    </SyncContext.Provider>
  );
}

export function useSync() {
  const context = useContext(SyncContext);
  if (!context) {
    return {
      isConnected: false,
      activeDevices: 1,
      lastSyncTime: null,
      remoteTyping: false,
      sendSyncEvent: () => {},
    };
  }
  return context;
}
