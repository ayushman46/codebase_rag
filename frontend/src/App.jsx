import React, { useEffect, useState } from 'react';
import useStore from './store/useStore';
import RepoInput from './components/RepoInput';
import RepoList from './components/RepoList';
import ChatWindow from './components/ChatWindow';
import { Menu, X, LogOut } from 'lucide-react';
import { supabase } from './api/supabase';

function App() {
  const { 
    fetchRepos, 
    repos, 
    pollStatus, 
    selectedRepo, 
    setSelectedRepo, 
    user, 
    setUser, 
    signInWithGoogle, 
    signInAnonymously,
    signOut 
  } = useStore();
  const [isDrawerOpen, setIsDrawerOpen] = useState(false);
  const [authLoading, setAuthLoading] = useState(true);

  // Initialize Auth session
  useEffect(() => {
    supabase.auth.getSession().then(({ data: { session } }) => {
      setUser(session?.user ?? null);
      setAuthLoading(false);
    });

    const { data: { subscription } } = supabase.auth.onAuthStateChange((_event, session) => {
      setUser(session?.user ?? null);
      setAuthLoading(false);
    });

    return () => subscription.unsubscribe();
  }, [setUser]);

  // Fetch repos once user is authenticated
  useEffect(() => {
    if (user) {
      fetchRepos();
    }
  }, [user, fetchRepos]);

  // Poll active statuses
  useEffect(() => {
    if (!user) return;
    const interval = setInterval(() => {
      repos.forEach(repo => {
        if (repo.status !== 'ready' && repo.status !== 'failed') {
          pollStatus(repo.repo_name);
        }
      });
    }, 5000);
    return () => clearInterval(interval);
  }, [repos, pollStatus, user]);

  // Automatically close drawer when a repo is selected
  useEffect(() => {
    if (selectedRepo) {
      setIsDrawerOpen(false);
    }
  }, [selectedRepo]);

  if (authLoading) {
    return (
      <div className="flex items-center justify-center h-screen w-full bg-warm-canvas text-ink-black">
        <span className="text-sm font-medium text-pewter tracking-widest animate-pulse uppercase">✦ Initializing Auth ✦</span>
      </div>
    );
  }

  return (
    <div className="relative h-screen w-full bg-warm-canvas text-ink-black font-abc-diatype overflow-hidden antialiased">
      
      {/* Sliding Drawer (Left) */}
      <div 
        className={`fixed top-0 left-0 h-full w-[320px] bg-pure-white border-r border-sand z-50 transform transition-transform duration-300 ease-in-out flex flex-col ${
          isDrawerOpen ? 'translate-x-0' : '-translate-x-full'
        }`}
      >
        <div className="p-6 border-b border-sand flex items-center justify-between">
          <div>
            <h1 className="text-heading-sm font-semibold tracking-tight text-ink-black">Codebase Intel</h1>
            <p className="text-caption text-warm-gray mt-0.5">My Index Console</p>
          </div>
          <button 
            onClick={() => setIsDrawerOpen(false)}
            className="p-1.5 hover:bg-warm-canvas rounded-lg text-slate transition-colors"
          >
            <X className="w-5 h-5" />
          </button>
        </div>

        <div className="flex-1 overflow-y-auto p-6">
          <div className="text-caption font-semibold text-stone uppercase tracking-wider mb-4">Indexed Repositories</div>
          {user ? (
            <RepoList />
          ) : (
            <p className="text-xs text-warm-gray">Sign in to view repositories.</p>
          )}
        </div>
      </div>

      {/* Drawer Overlay Backdrop */}
      {isDrawerOpen && (
        <div 
          onClick={() => setIsDrawerOpen(false)}
          className="fixed inset-0 bg-ink-black/10 backdrop-blur-[2px] z-40 transition-opacity"
        />
      )}

      {/* Main Workspace */}
      <div className="h-full w-full flex flex-col bg-warm-canvas relative overflow-hidden">
        {/* Classy Centered Navbar */}
        <nav className="w-full max-w-[1200px] mx-auto px-8 pt-12 pb-6 grid grid-cols-[1fr_auto_1fr] items-center bg-transparent shrink-0">
          
          {/* Left: Brand Wordmark */}
          <div 
            className="flex items-center space-x-2.5 cursor-pointer justify-self-start group"
            onClick={() => setSelectedRepo(null)}
          >
            <span className="text-ember-orange text-lg transform group-hover:scale-110 transition-transform">✦</span>
            <span className="text-base font-semibold tracking-tight text-ink-black">
              Codebase Intel
            </span>
          </div>
          
          {/* Center: Main Links */}
          <div className="flex items-center justify-center space-x-8 justify-self-center">
            {user && (
              <button 
                onClick={() => setIsDrawerOpen(true)}
                className="text-sm font-medium text-warm-gray hover:text-ember-orange transition-colors duration-200 flex items-center space-x-2"
              >
                <span>Codebases</span>
                <span className="px-1.5 py-0.5 bg-[#fff1ed] text-ember-orange text-[10px] font-bold rounded-badges border border-burnt-rust/10 leading-none">
                  {repos.length}
                </span>
              </button>
            )}
            <span className="text-sm font-medium text-warm-gray hover:text-ember-orange cursor-pointer transition-colors duration-200">
              Platform
            </span>
            <span className="text-sm font-medium text-warm-gray hover:text-ember-orange cursor-pointer transition-colors duration-200">
              Pricing
            </span>
            <span className="text-sm font-medium text-warm-gray hover:text-ember-orange cursor-pointer transition-colors duration-200">
              Docs
            </span>
          </div>
          
          {/* Right: Actions */}
          <div className="flex items-center space-x-6 justify-self-end">
            {selectedRepo && (
              <button 
                onClick={() => setSelectedRepo(null)}
                className="text-sm font-medium text-ember-orange hover:text-burnt-rust transition-colors duration-200 mr-2"
              >
                Close Chat
              </button>
            )}
            
            {user ? (
              <div className="flex items-center space-x-4">
                <div className="flex items-center space-x-2">
                  {user.user_metadata?.avatar_url ? (
                    <img 
                      src={user.user_metadata.avatar_url} 
                      alt="avatar" 
                      className="w-7 h-7 rounded-full border border-sand"
                    />
                  ) : (
                    <div className="w-7 h-7 rounded-full bg-peach-blush text-burnt-rust flex items-center justify-center text-xs font-bold uppercase">
                      {user.email ? user.email.slice(0, 2) : 'GS'}
                    </div>
                  )}
                  <span className="text-xs font-semibold text-charcoal max-w-[100px] truncate hidden md:inline">
                    {user.user_metadata?.full_name || (user.is_anonymous ? 'Guest' : user.email)}
                  </span>
                </div>
                <button 
                  onClick={signOut}
                  className="p-1.5 hover:bg-warm-canvas rounded-lg text-warm-gray hover:text-ink-black transition-colors"
                  title="Sign Out"
                >
                  <LogOut className="w-4 h-4" />
                </button>
              </div>
            ) : (
              <>
                <button 
                  onClick={signInWithGoogle}
                  className="text-sm font-medium text-warm-gray hover:text-ink-black transition-colors duration-200"
                >
                  Sign In
                </button>
                <button 
                  onClick={signInWithGoogle}
                  className="pill-button text-sm !py-2 !px-5 shadow-none font-medium leading-none"
                >
                  Start Free
                </button>
              </>
            )}
          </div>
        </nav>

        {/* Workspace body */}
        <div className="flex-1 overflow-hidden flex flex-col">
          {!selectedRepo ? (
            <div className="flex-grow flex flex-col items-center justify-center p-8 max-w-2xl mx-auto w-full mb-16">
              <div className="text-center space-y-6 w-full">
                <span className="text-caption font-medium text-warm-gray uppercase tracking-widest">
                  Cognitive System ✦ Agent 4
                </span>
                <h2 className="text-display heading-display text-ink-black leading-none">
                  Understand any codebase.
                </h2>
                
                {user ? (
                  <>
                    <p className="text-body text-pewter max-w-md mx-auto leading-relaxed">
                      Paste a public GitHub repository link to ingest and analyze it.
                    </p>
                    <div className="pt-8 w-full max-w-xl mx-auto">
                      <RepoInput />
                    </div>
                  </>
                ) : (
                  <div className="space-y-4 pt-8 max-w-md mx-auto flex flex-col items-center">
                    <p className="text-body text-pewter leading-relaxed mb-2">
                      Sign in with Google, or continue as a guest to test the codebase search engine.
                    </p>
                    <div className="flex items-center space-x-4">
                      <button 
                        onClick={signInWithGoogle}
                        className="pill-button text-sm !py-3 !px-6 shadow-none font-medium leading-none"
                      >
                        Sign In with Google
                      </button>
                      <button 
                        onClick={signInAnonymously}
                        className="outline-button text-sm !py-3 !px-6 font-medium leading-none transition-colors hover:bg-pure-white"
                      >
                        Continue as Guest
                      </button>
                    </div>
                  </div>
                )}
              </div>
            </div>
          ) : (
            <div className="flex-grow p-6 overflow-hidden flex flex-col max-w-5xl mx-auto w-full h-full mb-6">
              <ChatWindow />
            </div>
          )}
        </div>
      </div>
    </div>
  );
}

export default App;
