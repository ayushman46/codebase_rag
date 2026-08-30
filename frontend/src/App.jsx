import { lazy, Suspense, useEffect, useState } from 'react';
import { Navigate, Route, Routes } from 'react-router-dom';
import RequireAuth from './components/RequireAuth';
import SiteHeader from './components/SiteHeader';
import { supabase } from './api/supabase';
import { isIngestionActive } from './components/IngestionProgress';
import useStore from './store/useStore';

const AccountPage = lazy(() => import('./pages/AccountPage'));
const DashboardPage = lazy(() => import('./pages/DashboardPage'));
const DocsPage = lazy(() => import('./pages/DocsPage'));
const LandingPage = lazy(() => import('./pages/LandingPage'));
const PlatformPage = lazy(() => import('./pages/PlatformPage'));
const PricingPage = lazy(() => import('./pages/PricingPage'));

const MarketingLayout = ({ children }) => (
  <div className="min-h-screen bg-warm-canvas text-ink-black"><SiteHeader />{children}</div>
);

const PageLoader = () => <div className="flex min-h-[calc(100vh-5rem)] items-center justify-center text-sm font-medium uppercase tracking-widest text-pewter animate-pulse">Loading workspace…</div>;

const marketingPage = (page) => <Suspense fallback={<PageLoader />}><MarketingLayout>{page}</MarketingLayout></Suspense>;

function App() {
  const { fetchRepos, pollStatus, repos, setUser, user } = useStore();
  const [authLoading, setAuthLoading] = useState(true);

  useEffect(() => {
    let mounted = true;
    supabase.auth.getSession().then(({ data: { session } }) => {
      if (!mounted) return;
      setUser(session?.user ?? null);
      setAuthLoading(false);
    });

    const { data: { subscription } } = supabase.auth.onAuthStateChange((_event, session) => {
      if (!mounted) return;
      setUser(session?.user ?? null);
      setAuthLoading(false);
    });

    return () => {
      mounted = false;
      subscription.unsubscribe();
    };
  }, [setUser]);

  useEffect(() => {
    if (user) fetchRepos();
  }, [user, fetchRepos]);

  useEffect(() => {
    if (!user) return undefined;
    const interval = setInterval(() => {
      repos.forEach((repo) => {
        if (isIngestionActive(repo.status)) pollStatus(repo.repo_name);
      });
    }, 5000);
    return () => clearInterval(interval);
  }, [repos, pollStatus, user]);

  if (authLoading) {
    return <div className="flex h-screen w-full items-center justify-center bg-warm-canvas text-ink-black"><span className="text-center text-sm font-medium uppercase tracking-widest text-pewter animate-pulse">Initializing secure workspace</span></div>;
  }

  return (
    <Routes>
      <Route path="/" element={marketingPage(<LandingPage />)} />
      <Route path="/platform" element={marketingPage(<PlatformPage />)} />
      <Route path="/pricing" element={marketingPage(<PricingPage />)} />
      <Route path="/docs" element={marketingPage(<DocsPage />)} />
      <Route path="/app" element={<RequireAuth><Suspense fallback={<PageLoader />}><DashboardPage /></Suspense></RequireAuth>} />
      <Route path="/account" element={<RequireAuth>{marketingPage(<AccountPage />)}</RequireAuth>} />
      <Route path="*" element={<Navigate to="/" replace />} />
    </Routes>
  );
}

export default App;
