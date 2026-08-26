import axios from 'axios';

const api = axios.create({
  // Local development keeps the existing FastAPI port. Production uses the
  // same origin, so browser requests never need a separate backend URL.
  baseURL: import.meta.env.VITE_API_BASE_URL || (import.meta.env.DEV ? 'http://localhost:8000/api' : '/api'),
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
export const queryRepo = (repo_name, question, model_profile = 'fast') => api.post('/query', { repo_name, question, model_profile });
export const getConversation = (repo_name) => api.get(`/conversations/${encodeURIComponent(repo_name)}`);
export const getRepos = () => api.get('/repos');
export const getStatus = (repo_name) => api.get(`/status/${repo_name}`);
export const cancelIndexing = (repo_name) => api.post(`/repos/${encodeURIComponent(repo_name)}/cancel-indexing`);
export const reindexRepository = (repo_name) => api.post(`/repos/${encodeURIComponent(repo_name)}/reindex`);
