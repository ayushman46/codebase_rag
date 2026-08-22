import { X } from 'lucide-react';
import { useEffect, useState } from 'react';
import ChatWindow from '../components/ChatWindow';
import RepoInput from '../components/RepoInput';
import RepoList from '../components/RepoList';
import SiteHeader from '../components/SiteHeader';
import useStore from '../store/useStore';

const DashboardPage = () => {
  const { repos, selectedRepo, setSelectedRepo } = useStore();
  const [isDrawerOpen, setIsDrawerOpen] = useState(false);

  useEffect(() => {
    if (selectedRepo) setIsDrawerOpen(false);
  }, [selectedRepo]);

  return (
    <div className="min-h-screen bg-warm-canvas text-ink-black">
      <SiteHeader onOpenRepos={() => setIsDrawerOpen(true)} />

      <aside className={`fixed inset-y-0 left-0 z-50 flex w-[320px] flex-col border-r border-sand bg-pure-white shadow-xl transition-transform duration-300 ${isDrawerOpen ? 'translate-x-0' : '-translate-x-full'}`} aria-label="Indexed repositories">
        <div className="flex items-center justify-between border-b border-sand p-6">
          <div><h2 className="text-heading-sm font-semibold tracking-tight text-ink-black">Codebases</h2><p className="mt-0.5 text-caption text-warm-gray">Your index console</p></div>
          <button onClick={() => setIsDrawerOpen(false)} className="rounded-lg p-1.5 text-slate transition hover:bg-warm-canvas" aria-label="Close repository list"><X className="h-5 w-5" /></button>
        </div>
        <div className="flex-1 overflow-y-auto p-6"><p className="mb-4 text-caption font-semibold uppercase tracking-wider text-stone">Indexed repositories</p><RepoList /></div>
      </aside>
      {isDrawerOpen && <button className="fixed inset-0 z-40 cursor-default bg-ink-black/10 backdrop-blur-[2px]" onClick={() => setIsDrawerOpen(false)} aria-label="Close repository list" />}

      <main className="mx-auto flex min-h-[calc(100vh-5rem)] max-w-6xl flex-col px-5 py-8 sm:px-8">
        {!selectedRepo ? (
          <section className="m-auto w-full max-w-2xl pb-20 text-center">
            <span className="text-caption font-medium uppercase tracking-widest text-warm-gray">Private workspace ✦ Agent 4</span>
            <h1 className="heading-display mt-6 text-display text-ink-black">Understand any codebase.</h1>
            <p className="mx-auto mt-6 max-w-md text-body leading-relaxed text-pewter">Paste a public GitHub repository link to ingest and analyze it in your private workspace.</p>
            <div className="mx-auto mt-10 max-w-xl"><RepoInput /></div>
            {repos.length > 0 && <button onClick={() => setIsDrawerOpen(true)} className="mt-6 text-sm font-semibold text-ember-orange hover:text-burnt-rust">Browse {repos.length} indexed {repos.length === 1 ? 'codebase' : 'codebases'}</button>}
          </section>
        ) : (
          <section className="flex min-h-[calc(100vh-9rem)] flex-1 flex-col py-2"><div className="mb-4 flex justify-end"><button onClick={() => setSelectedRepo(null)} className="text-sm font-semibold text-ember-orange hover:text-burnt-rust">Close chat</button></div><ChatWindow /></section>
        )}
      </main>
    </div>
  );
};

export default DashboardPage;
