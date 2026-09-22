import axios from 'axios';

const API_BASE = import.meta.env.VITE_API_BASE || 'http://localhost:8000';

const createAdminClient = (adminKey) => {
  return axios.create({
    baseURL: API_BASE,
    headers: {
      'X-Admin-Key': adminKey,
    },
  });
};

export const adminApi = {
  getIngestionLogs: async (adminKey, params = {}) => {
    const client = createAdminClient(adminKey);
    const res = await client.get('/admin/ingestion-log', { params });
    return res.data;
  },

  ingestPdf: async (adminKey, formData) => {
    const client = createAdminClient(adminKey);
    // Let browser set the proper Content-Type with boundary for multipart/form-data
    const res = await client.post('/admin/ingest', formData, {
      headers: {
        'Content-Type': 'multipart/form-data'
      }
    });
    return res.data;
  }
};
