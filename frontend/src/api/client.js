import axios from 'axios';

const API_BASE = 'http://localhost:8000';

const client = axios.create({
  baseURL: API_BASE,
  headers: {
    'Content-Type': 'application/json',
  },
});

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
  sendMessage: async (data) => {
    const res = await client.post('/chat', data);
    return res.data;
  },
  getHistory: async (sessionId) => {
    const res = await client.get(`/history/${sessionId}`);
    return res.data;
  },
};

export const studentApi = {
  getSessions: async (studentId, subject = "Science") => {
    const res = await client.get('/sessions', { params: { student_id: studentId, subject } });
    return res.data.sessions;
  },
  getMemory: async (studentId, subject = "Science") => {
    const res = await client.get('/student/memory', { params: { student_id: studentId, subject } });
    return res.data.memory;
  },
  getProfile: async (studentId, subject = "Science") => {
    const res = await client.get('/student/profile', { params: { student_id: studentId, subject } });
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
  getYesterdayContext: async (student_id) => {
    const res = await client.get('/quiz/yesterday', { params: { student_id } });
    return res.data;
  },
  /** Past quiz attempt history */
  getHistory: async (student_id, subject = null) => {
    const params = { student_id };
    if (subject) params.subject = subject;
    const res = await client.get('/quiz/history', { params });
    return res.data.attempts;
  },
  /** Subject-level quiz feedback */
  getFeedback: async (student_id, subject) => {
    const res = await client.get(`/quiz/feedback/${subject}`, { params: { student_id } });
    return res.data;
  },
};

export default client;
