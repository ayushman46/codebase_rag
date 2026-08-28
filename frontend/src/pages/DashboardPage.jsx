import { X } from 'lucide-react';
import { useEffect, useState } from 'react';
import ChatWindow from '../components/ChatWindow';
import IngestionProgress, { isIngestionActive } from '../components/IngestionProgress';
import RepoInput from '../components/RepoInput';
import RepoList from '../components/RepoList';
import SiteHeader from '../components/SiteHeader';
import useStore from '../store/useStore';

const DashboardPage = () => {
  const { repos, selectedRepo, setSelectedRepo } = useStore();
  const [isDrawerOpen, setIsDrawerOpen] = useState(false);
  const activeRepos = repos.filter((repo) => isIngestionActive(repo.status));

  useEffect(() => {
    if (selectedRepo) setIsDrawerOpen(false);
  }, [selectedRepo]);

  return (
    <div className="min-h-screen bg-warm-canvas text-ink-black">
      <SiteHeader onOpenRepos={() => setIsDrawerOpen(true)} />

      <aside className={`fixed inset-y-0 left-0 z-50 flex w-full max-w-[360px] flex-col border-r border-sand bg-pure-white shadow-xl transition-transform duration-300 sm:w-[360px] ${isDrawerOpen ? 'translate-x-0' : '-translate-x-full'}`} aria-label="Indexed repositories">
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
            {activeRepos.length > 0 && (
              <div className="mx-auto mt-7 max-w-2xl space-y-3">
                {activeRepos.map((repo) => <IngestionProgress key={repo.id} repo={repo} />)}
              </div>
            )}
            {repos.length > 0 && <button onClick={() => setIsDrawerOpen(true)} className="mt-7 text-sm font-semibold text-ember-orange hover:text-burnt-rust">Browse codebases ({repos.length})</button>}
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
