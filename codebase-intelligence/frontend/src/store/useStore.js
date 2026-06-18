import { create } from 'zustand';

const useStore = create((set) => ({
  repos: {},
  selectedRepo: null,
  messages: [],
  isQuerying: false,
  isIngesting: false,
  
  setRepos: (repos) => set({ repos }),
  setSelectedRepo: (repoName) => set({ selectedRepo: repoName, messages: [] }),
  
  addMessage: (message) => set((state) => ({ 
    messages: [...state.messages, message] 
  })),
  
  setQuerying: (status) => set({ isQuerying: status }),
  setIngesting: (status) => set({ isIngesting: status }),
  
  updateRepoStatus: (repoName, statusData) => set((state) => ({
    repos: {
      ...state.repos,
      [repoName]: statusData
    }
  }))
}));

export default useStore;
