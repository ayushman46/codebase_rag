import { ArrowUpRight, Ellipsis, Loader2, Pencil, RefreshCw, Square, Trash2, X } from 'lucide-react';
import { useState } from 'react';
import useStore from '../store/useStore';
import IngestionProgress, { getIngestionStatus, isIngestionActive } from './IngestionProgress';

const RepoList = () => {
  const {
    repos, selectedRepo, setSelectedRepo, reindexRepo, cancelRepoIndexing, renameRepo, deleteRepo,
  } = useStore();
  const [openMenuId, setOpenMenuId] = useState(null);
  const [retryingRepoId, setRetryingRepoId] = useState(null);
  const [stoppingRepoId, setStoppingRepoId] = useState(null);
  const [dialog, setDialog] = useState(null);
  const [draftName, setDraftName] = useState('');
  const [actionError, setActionError] = useState('');
  const [isSaving, setIsSaving] = useState(false);

  const closeDialog = () => {
    if (!isSaving) {
      setDialog(null);
      setActionError('');
    }
  };

  const handleReindex = async (repo) => {
    setRetryingRepoId(repo.id);
    try {
      await reindexRepo(repo);
    } finally {
      setRetryingRepoId(null);
    }
  };

  const handleStop = async (repo) => {
    setStoppingRepoId(repo.id);
    try {
      await cancelRepoIndexing(repo);
    } finally {
      setStoppingRepoId(null);
    }
  };

  const openRename = (repo) => {
    setOpenMenuId(null);
    setActionError('');
    setDraftName(repo.repo_name);
    setDialog({ type: 'rename', repo });
  };

  const openDelete = (repo) => {
    setOpenMenuId(null);
    setActionError('');
    setDialog({ type: 'delete', repo });
  };

  const submitRename = async (event) => {
    event.preventDefault();
    const nextName = draftName.trim();
    if (!nextName) {
      setActionError('Enter a repository name.');
      return;
    }
    setIsSaving(true);
    setActionError('');
    try {
      await renameRepo(dialog.repo, nextName);
      setDialog(null);
    } catch (error) {
      setActionError(error.response?.data?.detail || 'Could not rename this repository.');
    } finally {
      setIsSaving(false);
    }
  };

  const confirmDelete = async () => {
    setIsSaving(true);
    setActionError('');
    try {
      await deleteRepo(dialog.repo);
      setDialog(null);
    } catch (error) {
      setActionError(error.response?.data?.detail || 'Could not delete this repository.');
    } finally {
      setIsSaving(false);
    }
  };

  if (repos.length === 0) {
    return <p className="py-5 text-sm leading-relaxed text-pewter">No codebases indexed yet.</p>;
  }

  return (
    <>
      <div className="border-y border-sand">
        {repos.map((repo) => {
          const isSelected = selectedRepo === repo.repo_name;
          const isReady = repo.status === 'ready';
          const isCancelled = repo.status === 'cancelled';
          const isActive = isIngestionActive(repo.status);
          const isRetrying = retryingRepoId === repo.id;
          const isStopping = stoppingRepoId === repo.id;
          const status = getIngestionStatus(repo.status, repo.error_message);
          const stateClass = isReady ? 'text-emerald-700' : repo.status === 'failed' ? 'text-red-600' : isCancelled ? 'text-pewter' : 'text-ember-orange';

          return (
            <article key={repo.id} className={`relative py-5 ${isSelected ? 'bg-pure-white' : ''}`} aria-current={isSelected ? 'page' : undefined}>
              <div className="flex items-start gap-3 px-2">
                <div className="min-w-0 flex-1">
                  <div className="flex items-start gap-3">
                    <div className="min-w-0 flex-1">
                      <p className="truncate text-base font-semibold tracking-tight text-ink-black">{repo.repo_name}</p>
                      <p className={`mt-1.5 text-xs font-semibold ${stateClass}`}>{isReady ? 'Ready' : repo.status === 'failed' ? 'Needs attention' : status.label}</p>
                    </div>
                    <span className="shrink-0 pt-0.5 text-xs text-warm-gray">{repo.chunk_count || 0} chunks</span>
                    <div className="relative -mr-1 -mt-1">
                      <button
                        type="button"
                        onClick={() => setOpenMenuId((id) => (id === repo.id ? null : repo.id))}
                        className="rounded-full p-1.5 text-warm-gray transition-colors hover:bg-warm-canvas hover:text-ink-black"
                        aria-label={`Repository actions for ${repo.repo_name}`}
                        aria-expanded={openMenuId === repo.id}
                      >
                        <Ellipsis className="h-4 w-4" aria-hidden="true" />
                      </button>
                      {openMenuId === repo.id && (
                        <div className="absolute right-0 top-8 z-10 w-36 border border-sand bg-pure-white py-1 text-sm shadow-lg" role="menu">
                          <button type="button" onClick={() => openRename(repo)} className="flex w-full items-center gap-2 px-3 py-2 text-left text-charcoal hover:bg-warm-canvas" role="menuitem">
                            <Pencil className="h-3.5 w-3.5" aria-hidden="true" /> Rename
                          </button>
                          <button type="button" onClick={() => openDelete(repo)} className="flex w-full items-center gap-2 px-3 py-2 text-left text-red-600 hover:bg-red-50" role="menuitem">
                            <Trash2 className="h-3.5 w-3.5" aria-hidden="true" /> Delete
                          </button>
                        </div>
                      )}
                    </div>
                  </div>

                  {isActive && <IngestionProgress repo={repo} compact />}
                  {repo.error_message && !isActive && (
                    <p className={`mt-3 border-l pl-3 text-xs leading-relaxed ${isCancelled ? 'border-sand text-pewter' : isReady ? 'border-amber-300 text-pewter' : 'border-red-300 text-red-600'}`}>{repo.error_message}</p>
                  )}

                  <div className="mt-4 flex flex-wrap items-center gap-x-4 gap-y-2 text-sm font-semibold">
                    {isReady && (
                      <button type="button" onClick={() => setSelectedRepo(repo.repo_name)} className="inline-flex items-center gap-1.5 text-ink-black transition-colors hover:text-ember-orange">
                        Open chat <ArrowUpRight className="h-3.5 w-3.5" aria-hidden="true" />
                      </button>
                    )}
                    {(repo.status === 'failed' || isCancelled) && (
                      <button type="button" onClick={() => handleReindex(repo)} disabled={isRetrying} className="inline-flex items-center gap-1.5 text-ember-orange transition-colors hover:text-burnt-rust disabled:cursor-wait disabled:opacity-60">
                        {isRetrying ? <Loader2 className="h-3.5 w-3.5 animate-spin" aria-hidden="true" /> : <RefreshCw className="h-3.5 w-3.5" aria-hidden="true" />}
                        {isRetrying ? 'Queueing…' : 'Re-index'}
                      </button>
                    )}
                    {isActive && (
                      <button type="button" onClick={() => handleStop(repo)} disabled={isStopping} className="inline-flex items-center gap-1.5 text-pewter transition-colors hover:text-ink-black disabled:cursor-wait disabled:opacity-60">
                        {isStopping ? <Loader2 className="h-3.5 w-3.5 animate-spin" aria-hidden="true" /> : <Square className="h-3 w-3" aria-hidden="true" />}
                        {isStopping ? 'Stopping…' : 'Stop indexing'}
                      </button>
                    )}
                  </div>
                </div>
              </div>
            </article>
          );
        })}
      </div>

      {dialog && (
        <div className="fixed inset-0 z-[60] grid place-items-center bg-ink-black/20 p-5" role="presentation" onMouseDown={closeDialog}>
          <section className="w-full max-w-sm border border-sand bg-pure-white p-5 shadow-xl" role="dialog" aria-modal="true" aria-labelledby="repository-dialog-title" onMouseDown={(event) => event.stopPropagation()}>
            <div className="flex items-start justify-between gap-4">
              <div>
                <h3 id="repository-dialog-title" className="text-lg font-semibold tracking-tight text-ink-black">{dialog.type === 'rename' ? 'Rename codebase' : 'Delete codebase'}</h3>
                <p className="mt-1.5 text-sm leading-relaxed text-pewter">
                  {dialog.type === 'rename'
                    ? 'Choose a clear name for this workspace.'
                    : `Delete ${dialog.repo.repo_name} and its indexed source and conversation history.`}
                </p>
              </div>
              <button type="button" onClick={closeDialog} disabled={isSaving} className="-mr-1 -mt-1 p-1 text-warm-gray hover:text-ink-black" aria-label="Close dialog"><X className="h-4 w-4" /></button>
            </div>

            {dialog.type === 'rename' ? (
              <form className="mt-5" onSubmit={submitRename}>
                <label className="sr-only" htmlFor="repository-name">Repository name</label>
                <input id="repository-name" autoFocus value={draftName} maxLength={200} onChange={(event) => setDraftName(event.target.value)} className="h-11 w-full border border-sand bg-warm-canvas px-3 text-sm text-ink-black outline-none focus:border-stone" />
                {actionError && <p className="mt-3 text-sm text-red-600" role="alert">{actionError}</p>}
                <div className="mt-5 flex justify-end gap-3 text-sm font-semibold">
                  <button type="button" onClick={closeDialog} disabled={isSaving} className="text-pewter hover:text-ink-black">Cancel</button>
                  <button type="submit" disabled={isSaving} className="text-ember-orange hover:text-burnt-rust disabled:opacity-60">{isSaving ? 'Saving…' : 'Save name'}</button>
                </div>
              </form>
            ) : (
              <div className="mt-5">
                {actionError && <p className="mb-3 text-sm text-red-600" role="alert">{actionError}</p>}
                <div className="flex justify-end gap-3 text-sm font-semibold">
                  <button type="button" onClick={closeDialog} disabled={isSaving} className="text-pewter hover:text-ink-black">Cancel</button>
                  <button type="button" onClick={confirmDelete} disabled={isSaving} className="text-red-600 hover:text-red-800 disabled:opacity-60">{isSaving ? 'Deleting…' : 'Delete repository'}</button>
                </div>
              </div>
            )}
          </section>
        </div>
      )}
    </>
  );
};

export default RepoList;
