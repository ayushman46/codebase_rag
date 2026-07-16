import axios from 'axios';

const api = axios.create({
  baseURL: 'http://localhost:8000/api',
});

// Interceptor to automatically attach Supabase Session Token
api.interceptors.request.use((config) => {
  const keys = Object.keys(localStorage);
  const sbKey = keys.find(k => k.startsWith('sb-') && k.endsWith('-auth-token'));
  if (sbKey) {
    try {
      const data = JSON.parse(localStorage.getItem(sbKey));
      const token = data?.access_token;
      if (token) {
        config.headers.Authorization = `Bearer ${token}`;
      }
    } catch (e) {
      console.error("Error reading Supabase token from local storage:", e);
    }
  }
  return config;
});

export const ingestRepo = (github_url) => api.post('/ingest', { github_url });
export const queryRepo = (repo_name, question) => api.post('/query', { repo_name, question });
export const getRepos = () => api.get('/repos');
export const getStatus = (repo_name) => api.get(`/status/${repo_name}`);
