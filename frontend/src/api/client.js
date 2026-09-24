import axios from 'axios';

const normalizeApiUrl = (raw) => {
  if (!raw || typeof raw !== 'string') return '';
  let url = raw.trim().replace(/\/+$/, '');
  if (!url) return '';
  if (!/^https?:\/\//i.test(url)) {
    // If user provided a domain without protocol (e.g. "vishwalpha-ai-tutor-production.up.railway.app")
    url = (url.includes('localhost') || url.startsWith('127.0.0.1'))
      ? `http://${url}`
      : `https://${url}`;
  }
  return url;
};

export const PROD_API = 'https://vishwalpha-ai-tutor-production.up.railway.app';
const rawConfiguredApi = import.meta.env.API_URL || import.meta.env.API_BASE;
export const API_BASE = normalizeApiUrl(rawConfiguredApi) || (import.meta.env.PROD ? PROD_API : 'http://localhost:8000');

const client = axios.create({
  baseURL: API_BASE,
  headers: {
    'Content-Type': 'application/json',
  },
});

// ── Module-level auth cache (avoids JSON.parse on every request) ──────────
let _cachedStudent = null;
const _getStudent = () => {
  if (!_cachedStudent) {
    const saved = localStorage.getItem('vishwalpha_student');
    if (saved) _cachedStudent = JSON.parse(saved);
  }
  return _cachedStudent;
};
export const clearStudentCache = () => { _cachedStudent = null; };

// Interceptor to attach JWT token
client.interceptors.request.use((config) => {
  const data = _getStudent();
  if (data?.access_token) {
    config.headers.Authorization = `Bearer ${data.access_token}`;
  }
  return config;
}, (error) => {
  return Promise.reject(error);
});

// Response interceptor for automatic 401 token refresh and session recovery
client.interceptors.response.use(
  (response) => response,
  async (error) => {
    const originalRequest = error.config;

    // If 401 Unauthorized and not already retrying and not a login/register attempt
    if (error.response?.status === 401 && originalRequest && !originalRequest._retry && !originalRequest.url?.includes('/auth/')) {
      originalRequest._retry = true;

      const studentData = _getStudent();

      if (studentData?.refresh_token) {
        try {
          // BL-08 fix: send refresh token in body, not URL query param
          const refreshRes = await axios.post(`${API_BASE}/auth/refresh`, {
            refresh_token: studentData.refresh_token
          });
          const newAccessToken = refreshRes.data.access_token;
          studentData.access_token = newAccessToken;
          _cachedStudent = studentData;
          localStorage.setItem('vishwalpha_student', JSON.stringify(studentData));

          originalRequest.headers.Authorization = `Bearer ${newAccessToken}`;
          return client(originalRequest);
        } catch (refreshErr) {
          _cachedStudent = null;
          localStorage.removeItem('vishwalpha_student');
          if (typeof window !== 'undefined' && window.location.pathname !== '/') {
            window.location.href = '/';
          }
          return Promise.reject(refreshErr);
        }
      } else {
        _cachedStudent = null;
        localStorage.removeItem('vishwalpha_student');
        if (typeof window !== 'undefined' && window.location.pathname !== '/') {
          window.location.href = '/';
        }
      }
    }

    return Promise.reject(error);
  }
);

export const authApi = {
  login: async (username, password) => {
    const res = await client.post('/auth/login', { username, password });
    return res.data;
  },
  register: async (data) => {
    const res = await client.post('/auth/register', data);
    return res.data;
  },
};

export const chatApi = {
  // Legacy non-streaming call (if still needed)
  sendMessage: async (data) => {
    const res = await client.post('/chat', data);
    return res.data;
  },
  
  // New SSE streaming call — returns an AbortController so caller can cancel on unmount.
  // FE-02: Hard 90-second timeout via AbortController.
  // FE-03: Caller must call controller.abort() in useEffect cleanup.
  sendMessageStream: (data, onChunk, onDone, onError) => {
    const controller = new AbortController();
    const timeout = setTimeout(() => controller.abort(), 90_000);

    (async () => {
      let token = '';
      const saved = _getStudent();
      if (saved?.access_token) token = saved.access_token;

      try {
        const response = await fetch(`${API_BASE}/chat/stream`, {
          method: 'POST',
          headers: {
            'Content-Type': 'application/json',
            ...(token ? { 'Authorization': `Bearer ${token}` } : {})
          },
          body: JSON.stringify(data),
          signal: controller.signal,
        });

        if (!response.ok) {
          let errorDetail = 'Network response was not ok';
          try {
            const errBody = await response.json();
            if (errBody.detail) errorDetail = errBody.detail;
          } catch (e) {}
          throw new Error(errorDetail);
        }

        const reader = response.body.getReader();
        const decoder = new TextDecoder('utf-8');
        let buffer = '';

        while (true) {
          const { done, value } = await reader.read();
          if (done) break;

          buffer += decoder.decode(value, { stream: true });

          const lines = buffer.split('\n');
          buffer = lines.pop(); // Keep the last incomplete line in the buffer

          for (const line of lines) {
            if (line.startsWith('data: ')) {
              const dataStr = line.slice(6);
              if (!dataStr) continue;
              try {
                const parsed = JSON.parse(dataStr);
                if (parsed.type === 'token') {
                  onChunk(parsed.content);
                } else if (parsed.type === 'done') {
                  onDone(parsed);
                } else if (parsed.type === 'error') {
                  onError(new Error(parsed.detail));
                } else if (parsed.type === 'meta') {
                  onChunk('', parsed);
                }
              } catch (err) {
                console.warn('Failed to parse SSE JSON:', dataStr, err);
              }
            }
          }
        }
      } catch (err) {
        if (err.name !== 'AbortError') {
          onError(err);
        }
      } finally {
        clearTimeout(timeout);
      }
    })();

    return controller;  // caller: store in ref and call controller.abort() on unmount
  },
  
  getHistory: async (sessionId) => {
    const res = await client.get(`/history/${sessionId}`);
    return res.data;
  },

  activateBranch: async (sessionId, messageId) => {
    const res = await client.patch(`/conversations/${sessionId}/messages/${messageId}/activate`);
    return res.data;
  },

  sendFeedback: async (messageId, rating, feedbackText = null) => {
    const res = await client.post('/chat/feedback', {
      message_id: messageId,
      rating,
      feedback_text: feedbackText
    });
    return res.data;
  },
};

export const spacesApi = {
  getSpaces: async (subject = null) => {
    const params = {};
    if (subject) params.subject = subject;
    const res = await client.get('/spaces', { params });
    return res.data.spaces;
  },
  createSpace: async (data) => {
    const res = await client.post('/spaces', data);
    return res.data;
  },
  updateSpace: async (spaceId, data) => {
    const res = await client.patch(`/spaces/${spaceId}`, data);
    return res.data;
  },
  deleteSpace: async (spaceId) => {
    const res = await client.delete(`/spaces/${spaceId}`);
    return res.data;
  },
};

export const searchApi = {
  searchConversations: async (q, limit = 20) => {
    const res = await client.get('/conversations/search', { params: { q, limit } });
    return res.data.results;
  },
};

export const shareApi = {
  createShareLink: async (sessionId) => {
    const res = await client.post(`/conversations/${sessionId}/share`);
    return res.data;
  },
  getSharedConversation: async (token) => {
    const res = await client.get(`/share/${token}`);
    return res.data;
  },
};

export const studentApi = {
  getSessions: async (subject = null, studySpaceId = null) => {
    const params = {};
    if (subject) params.subject = subject;
    if (studySpaceId) params.study_space_id = studySpaceId;
    const res = await client.get('/sessions', { params });
    return res.data.sessions;
  },
  getMemory: async (subject = null) => {
    const params = {};
    if (subject) params.subject = subject;
    const res = await client.get('/student/memory', { params });
    return res.data.memory;
  },
  getProfile: async (subject = null) => {
    const params = {};
    if (subject) params.subject = subject;
    const res = await client.get('/student/profile', { params });
    return res.data;
  },
  getSessionRemark: async (sessionId) => {
    const res = await client.get(`/sessions/${sessionId}/remark`);
    return res.data.remark;
  },
  updateMetrics: async (sessionId, metrics) => {
    const res = await client.post(`/session/${sessionId}/metrics`, { metrics });
    return res.data;
  },
};

export const quizApi = {
  /** Generate a quiz. Returns { attempt_id, questions: [...] } */
  generate: async (data) => {
    const res = await client.post('/quiz/generate', data);
    return res.data;
  },
  /** Submit one answer. Returns { is_correct, correct_index, correct_answer, explanation } */
  submitAnswer: async (data) => {
    const res = await client.post('/quiz/answer', data);
    return res.data;
  },
  /** Finish the quiz. Returns { score, total, correct, passed, ai_feedback, metrics_impact } */
  finish: async (attempt_id, session_id = '') => {
    const res = await client.post('/quiz/finish', { attempt_id, session_id });
    return res.data;
  },
  /** Yesterday context for session-start banner */
  getYesterdayContext: async () => {
    const res = await client.get('/quiz/yesterday');
    return res.data;
  },
  /** Past quiz attempt history */
  getHistory: async (subject = null) => {
    const params = {};
    if (subject) params.subject = subject;
    const res = await client.get('/quiz/history', { params });
    return res.data.attempts;
  },
  /** Subject-level quiz feedback */
  getFeedback: async (subject) => {
    const res = await client.get(`/quiz/feedback/${subject}`);
    return res.data;
  },
};

export const attachmentsApi = {
  upload: async (file) => {
    const formData = new FormData();
    formData.append('file', file);
    const res = await client.post('/attachments/upload', formData, {
      headers: {
        'Content-Type': 'multipart/form-data',
      },
    });
    return res.data;
  },
};

export default client;
