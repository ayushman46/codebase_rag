import { create } from 'zustand';
import { getRepos, getStatus, queryRepo } from '../api/client';
import { supabase } from '../api/supabase';

const useStore = create((set, get) => ({
  repos: [],
  selectedRepo: null,
  messages: [],
  isQuerying: false,
  isIngesting: false,
  user: null,

  setUser: (user) => set({ user }),

  signInWithGoogle: async () => {
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
      alert("Failed to initialize Google Sign-In");
    }
  },

  signOut: async () => {
    try {
      const { error } = await supabase.auth.signOut();
      if (error) throw error;
      set({ user: null, selectedRepo: null, messages: [], repos: [] });
    } catch (e) {
      console.error("Sign-out error:", e);
    }
  },

  setSelectedRepo: (repoName) => {
    set({ selectedRepo: repoName, messages: [] });
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
