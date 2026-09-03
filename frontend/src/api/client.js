import axios from 'axios';
import { supabase } from './supabase';

const api = axios.create({
  // Local development keeps the existing FastAPI port. Production uses the
  // same origin, so browser requests never need a separate backend URL.
  baseURL: import.meta.env.VITE_API_BASE_URL || (import.meta.env.DEV ? 'http://localhost:8000/api' : '/api'),
  // Bound stalled network requests so the UI can recover instead of staying
  // in an indefinite loading state. The backend provider itself has a 90s
  // timeout; this leaves room for retrieval plus one provider retry.
  timeout: 120000,
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
export const queryRepo = (repo_name, question, model_profile = 'fast', workflow = 'general', config = {}) => api.post('/query', { repo_name, question, model_profile, workflow }, config);
export const getConversation = (repo_name, config = {}) => api.get(`/conversations/${encodeURIComponent(repo_name)}`, config);
export const getRepos = () => api.get('/repos');
export const renameRepository = (repo_name, new_repo_name) => api.patch(`/repos/${encodeURIComponent(repo_name)}`, { repo_name: new_repo_name });
export const deleteRepository = (repo_name) => api.delete(`/repos/${encodeURIComponent(repo_name)}`);
export const getStatus = (repo_name) => api.get(`/status/${encodeURIComponent(repo_name)}`);
export const getStatuses = (config = {}) => api.get('/repos/statuses', config);
export const cancelIndexing = (repo_name) => api.post(`/repos/${encodeURIComponent(repo_name)}/cancel-indexing`);
export const reindexRepository = (repo_name) => api.post(`/repos/${encodeURIComponent(repo_name)}/reindex`);
export const getRepositoryImpact = (repo_name, file_path, config = {}) => api.get(
  `/repos/${encodeURIComponent(repo_name)}/impact`,
  { params: { file_path, limit: 20 }, ...config },
);
export const getAccountUsage = () => api.get('/account/usage');
export const createTeamOrder = () => api.post('/create-order', { plan: 'team' });
export const verifyTeamPayment = (payment) => api.post('/verify-payment', payment);
