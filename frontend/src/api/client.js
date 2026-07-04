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

export default client;
