import { create } from 'zustand';
import { cancelIndexing, deleteRepository, getConversation, getRepos, getStatus, queryRepo, reindexRepository, renameRepository } from '../api/client';
import { isSupabaseConfigured, supabase } from '../api/supabase';

const useStore = create((set, get) => ({
  repos: [],
  selectedRepo: null,
  messages: [],
  isQuerying: false,
  queryEpoch: 0,
  isHistoryLoading: false,
  isIngesting: false,
  isSigningIn: false,
  authError: null,
  reposError: null,
  user: null,

  setUser: (user) => set({ user }),

  clearAuthError: () => set({ authError: null }),

  signInWithGoogle: async () => {
    if (!isSupabaseConfigured) {
      set({
        authError: 'Google sign-in is unavailable because Supabase environment variables are missing.',
      });
      return;
    }

    set({ isSigningIn: true, authError: null });
    try {
      const { error } = await supabase.auth.signInWithOAuth({
        provider: 'google',
        options: {
          redirectTo: window.location.origin
        }
      });
      if (error) throw error;
    } catch (e) {
      console.error("Sign-in error:", e);
      set({ authError: e.message || 'Google sign-in could not be started. Please try again.' });
    } finally {
      set({ isSigningIn: false });
    }
  },

  signOut: async () => {
    try {
      const { error } = await supabase.auth.signOut();
      if (error) throw error;
      set((state) => ({ user: null, selectedRepo: null, messages: [], repos: [], isHistoryLoading: false, isQuerying: false, queryEpoch: state.queryEpoch + 1 }));
    } catch (e) {
      console.error("Sign-out error:", e);
    }
  },

  setSelectedRepo: async (repoName) => {
    if (!repoName) {
      set((state) => ({ selectedRepo: null, messages: [], isHistoryLoading: false, isQuerying: false, queryEpoch: state.queryEpoch + 1 }));
      return;
    }
    set((state) => ({ selectedRepo: repoName, messages: [], isHistoryLoading: true, isQuerying: false, queryEpoch: state.queryEpoch + 1 }));
    try {
      const res = await getConversation(repoName);
      if (get().selectedRepo === repoName) {
        set({ messages: res.data.messages || [], isHistoryLoading: false });
      }
    } catch (e) {
      console.error(e);
      if (get().selectedRepo === repoName) set({ messages: [], isHistoryLoading: false });
    }
  },

  fetchRepos: async () => {
    try {
      const res = await getRepos();
      set({ repos: res.data, reposError: null });
    } catch (e) {
      console.error(e);
      set({ reposError: 'Could not load your repositories. Please check your connection and try again.' });
    }
  },

  pollStatus: async (repoName) => {
    try {
      const res = await getStatus(repoName);
      set((state) => ({
        repos: state.repos.map(r => r.repo_name === repoName ? { ...r, ...res.data } : r)
      }));
    } catch (e) {
      console.error(e);
    }
  },

  setIngesting: (val) => set({ isIngesting: val }),

  reindexRepo: async (repo) => {
    await reindexRepository(repo.repo_name);
    set((state) => ({
      repos: state.repos.map((item) => item.id === repo.id
        ? { ...item, status: 'queued', chunk_count: 0, error_message: null }
        : item),
    }));
  },

  cancelRepoIndexing: async (repo) => {
    await cancelIndexing(repo.repo_name);
    set((state) => ({
      repos: state.repos.map((item) => item.id === repo.id
        ? { ...item, status: 'cancelled', chunk_count: 0, error_message: 'Indexing stopped by you.' }
        : item),
    }));
  },

  renameRepo: async (repo, nextName) => {
    const response = await renameRepository(repo.repo_name, nextName);
    const repoName = response.data.repo_name;
    set((state) => ({
      repos: state.repos.map((item) => item.id === repo.id ? { ...item, repo_name: repoName } : item),
      selectedRepo: state.selectedRepo === repo.repo_name ? repoName : state.selectedRepo,
    }));
    return repoName;
  },

  deleteRepo: async (repo) => {
    await deleteRepository(repo.repo_name);
    set((state) => ({
      repos: state.repos.filter((item) => item.id !== repo.id),
      ...(state.selectedRepo === repo.repo_name
        ? { selectedRepo: null, messages: [], isHistoryLoading: false }
        : {}),
    }));
  },

  askQuestion: async (question, modelProfile = 'fast') => {
    const repo = get().selectedRepo;
    if (!repo) return;
    const queryEpoch = get().queryEpoch;

    const userMsg = { id: crypto.randomUUID(), role: 'user', content: question };
    set((state) => ({ 
      messages: [...state.messages, userMsg],
      isQuerying: true
    }));

    try {
      const res = await queryRepo(repo, question, modelProfile);
      const data = res.data;
      
      const assistantMsg = {
        id: crypto.randomUUID(),
        role: 'assistant',
        content: data.answer,
        citations: data.citations,
        tool_calls: data.tool_calls,
        mode: data.mode,
        latency_ms: data.latency_ms,
        model_profile: data.model_profile,
      };
      
      set((state) => (
        state.selectedRepo === repo && state.queryEpoch === queryEpoch
          ? { messages: [...state.messages, assistantMsg], isQuerying: false }
          : {}
      ));
    } catch (e) {
      const detail = e.response?.data?.detail;
      const message = typeof detail === 'string' && detail.trim()
        ? detail
        : 'This question could not be completed right now. Your repository and conversation are unchanged; please try again shortly.';
      set((state) => (
        state.selectedRepo === repo && state.queryEpoch === queryEpoch
          ? { messages: [...state.messages, { id: crypto.randomUUID(), role: 'assistant', content: message, mode: 'error' }], isQuerying: false }
          : {}
      ));
    }
  }
}));

export default useStore;
