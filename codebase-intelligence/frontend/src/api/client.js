import axios from 'axios';

const api = axios.create({
  baseURL: 'http://localhost:8000/api',
});

export const getRepos = () => api.get('/repos');
export const getRepoStatus = (repoName) => api.get(`/status/${repoName}`);
export const ingestRepo = (githubUrl) => api.post('/ingest', { github_url: githubUrl });
export const queryRepo = (repoName, question) => api.post('/query', { repo_name: repoName, question });
export const deleteRepo = (repoName) => api.delete(`/repos/${repoName}`);

export default api;
