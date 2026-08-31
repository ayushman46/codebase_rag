import axios from 'axios';
import { supabase } from './supabase';

const api = axios.create({
  // Local development keeps the existing FastAPI port. Production uses the
  // same origin, so browser requests never need a separate backend URL.
  baseURL: import.meta.env.VITE_API_BASE_URL || (import.meta.env.DEV ? 'http://localhost:8000/api' : '/api'),
});

// Ask the SDK for the current session instead of scanning every local-storage
// entry. The SDK owns session persistence and refresh behaviour.
api.interceptors.request.use(async (config) => {
  const { data: { session } } = await supabase.auth.getSession();
  if (session?.access_token) {
    config.headers.Authorization = `Bearer ${session.access_token}`;
  }
  return config;
});

export const ingestRepo = (github_url) => api.post('/ingest', { github_url });
export const queryRepo = (repo_name, question, model_profile = 'fast', workflow = 'general') => api.post('/query', { repo_name, question, model_profile, workflow });
export const getConversation = (repo_name) => api.get(`/conversations/${encodeURIComponent(repo_name)}`);
export const getRepos = () => api.get('/repos');
export const renameRepository = (repo_name, new_repo_name) => api.patch(`/repos/${encodeURIComponent(repo_name)}`, { repo_name: new_repo_name });
export const deleteRepository = (repo_name) => api.delete(`/repos/${encodeURIComponent(repo_name)}`);
export const getStatus = (repo_name) => api.get(`/status/${encodeURIComponent(repo_name)}`);
export const cancelIndexing = (repo_name) => api.post(`/repos/${encodeURIComponent(repo_name)}/cancel-indexing`);
export const reindexRepository = (repo_name) => api.post(`/repos/${encodeURIComponent(repo_name)}/reindex`);
