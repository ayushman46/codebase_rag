import { create } from 'zustand';
import { cancelIndexing, getConversation, getRepos, getStatus, queryRepo, reindexRepository } from '../api/client';
import { isSupabaseConfigured, supabase } from '../api/supabase';

const useStore = create((set, get) => ({
  repos: [],
  selectedRepo: null,
  messages: [],
  isQuerying: false,
  isHistoryLoading: false,
  isIngesting: false,
  isSigningIn: false,
  authError: null,
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
      set({ user: null, selectedRepo: null, messages: [], repos: [], isHistoryLoading: false });
    } catch (e) {
      console.error("Sign-out error:", e);
    }
  },

  setSelectedRepo: async (repoName) => {
    if (!repoName) {
      set({ selectedRepo: null, messages: [], isHistoryLoading: false });
      return;
    }
    set({ selectedRepo: repoName, messages: [], isHistoryLoading: true });
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
      set({ repos: res.data });
    } catch (e) {
      console.error(e);
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

  askQuestion: async (question) => {
    const repo = get().selectedRepo;
    if (!repo) return;

    const userMsg = { role: 'user', content: question };
    set((state) => ({ 
      messages: [...state.messages, userMsg],
      isQuerying: true
    }));

    try {
      const res = await queryRepo(repo, question);
      const data = res.data;
      
      const assistantMsg = {
        role: 'assistant',
        content: data.answer,
        citations: data.citations,
        tool_calls: data.tool_calls,
        mode: data.mode,
        latency_ms: data.latency_ms
      };
      
      set((state) => ({
        messages: [...state.messages, assistantMsg],
        isQuerying: false
      }));
    } catch (e) {
      set((state) => ({
        messages: [...state.messages, { role: 'assistant', content: 'Sorry, an error occurred.' }],
        isQuerying: false
      }));
    }
  }
}));

export default useStore;
