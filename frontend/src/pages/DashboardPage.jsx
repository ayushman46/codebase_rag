import { X } from 'lucide-react';
import { useEffect, useRef, useState } from 'react';
import ChatWindow from '../components/ChatWindow';
import IngestionProgress, { isIngestionActive } from '../components/IngestionProgress';
import RepoInput from '../components/RepoInput';
import RepoList from '../components/RepoList';
import SiteHeader from '../components/SiteHeader';
import useStore from '../store/useStore';

const DashboardPage = () => {
  const { repos, reposError, selectedRepo, setSelectedRepo } = useStore();
  const [isDrawerOpen, setIsDrawerOpen] = useState(false);
  const drawerRef = useRef(null);
  const drawerInvokerRef = useRef(null);
  const activeRepos = repos.filter((repo) => isIngestionActive(repo.status));

  useEffect(() => {
    if (selectedRepo) setIsDrawerOpen(false);
  }, [selectedRepo]);

  useEffect(() => {
    if (!isDrawerOpen) return undefined;
    const previouslyFocused = drawerInvokerRef.current || document.activeElement;
    drawerRef.current?.querySelector('button, a[href], input')?.focus();
    const onKeyDown = (event) => {
      if (event.key === 'Escape') {
        setIsDrawerOpen(false);
        return;
      }
      if (event.key !== 'Tab' || !drawerRef.current) return;
      const focusable = [...drawerRef.current.querySelectorAll('a[href], button:not([disabled]), input:not([disabled]), select:not([disabled]), textarea:not([disabled]), [tabindex]:not([tabindex="-1"])')];
      if (!focusable.length) return;
      const first = focusable[0];
      const last = focusable[focusable.length - 1];
      if (event.shiftKey && document.activeElement === first) {
        event.preventDefault();
        last.focus();
      } else if (!event.shiftKey && document.activeElement === last) {
        event.preventDefault();
        first.focus();
      }
    };
    document.addEventListener('keydown', onKeyDown);
    return () => {
      document.removeEventListener('keydown', onKeyDown);
      previouslyFocused?.focus?.();
    };
  }, [isDrawerOpen]);

  const openDrawer = () => {
    drawerInvokerRef.current = document.activeElement;
    setIsDrawerOpen(true);
  };

  return (
    <div className="min-h-screen bg-warm-canvas text-ink-black">
      <SiteHeader onOpenRepos={openDrawer} />

      <aside ref={drawerRef} inert={isDrawerOpen ? undefined : ''} aria-hidden={!isDrawerOpen} className={`fixed inset-y-0 left-0 z-50 flex w-full max-w-[360px] flex-col border-r border-sand bg-pure-white shadow-xl transition-transform duration-300 sm:w-[360px] ${isDrawerOpen ? 'translate-x-0' : '-translate-x-full'}`} role="dialog" aria-modal="true" aria-label="Indexed repositories">
        <div className="flex items-center justify-between border-b border-sand px-5 py-6 sm:px-6">
          <div><h2 className="text-2xl font-semibold tracking-tight text-ink-black">Codebases</h2><p className="mt-1 text-sm text-warm-gray">Your repositories</p></div>
          <button onClick={() => setIsDrawerOpen(false)} className="p-2 text-slate transition-colors hover:text-ink-black" aria-label="Close repository list"><X className="h-5 w-5" /></button>
        </div>
        <div className="flex-1 overflow-y-auto px-5 py-6 sm:px-6"><p className="mb-3 text-caption font-semibold uppercase tracking-wider text-stone">Indexed repositories</p><RepoList /></div>
      </aside>
      {isDrawerOpen && <button className="fixed inset-0 z-40 cursor-default bg-ink-black/10 backdrop-blur-[2px]" onClick={() => setIsDrawerOpen(false)} aria-label="Close repository list" />}

      <main className={`content-shell flex min-h-[calc(100vh-5rem)] flex-col ${selectedRepo ? 'py-4 sm:py-6' : 'justify-center py-12 sm:py-16'}`}>
        {!selectedRepo ? (
          <section className="mx-auto w-full max-w-3xl text-center">
            <h1 className="heading-display landing-title text-ink-black">Understand any codebase.</h1>
            <p className="mx-auto mt-7 max-w-xl text-body leading-relaxed text-pewter">Paste a public GitHub repository link to index its source and explore it with grounded answers.</p>
            <div className="mx-auto mt-9 max-w-2xl"><RepoInput /></div>
            {reposError && (
              <div className="mx-auto mt-5 max-w-2xl rounded-2xl border border-red-200 bg-red-50 px-4 py-3 text-left text-sm leading-relaxed text-red-700" role="alert">
                {reposError}
              </div>
            )}
            {activeRepos.length > 0 && (
              <div className="mx-auto mt-7 max-w-2xl space-y-3">
                {activeRepos.map((repo) => <IngestionProgress key={repo.id} repo={repo} />)}
              </div>
            )}
            {repos.length > 0 && <button onClick={openDrawer} className="mt-7 min-h-11 text-sm font-semibold text-ember-orange hover:text-burnt-rust">Browse codebases ({repos.length})</button>}
          </section>
        ) : (
          <section className="flex flex-1 flex-col">
            <ChatWindow onClose={() => setSelectedRepo(null)} />
          </section>
        )}
      </main>
    </div>
  );
};

export default DashboardPage;
