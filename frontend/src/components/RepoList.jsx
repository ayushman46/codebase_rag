import { ArrowUpRight, Ellipsis, Loader2, Pencil, RefreshCw, Square, Trash2, X } from 'lucide-react';
import { useEffect, useRef, useState } from 'react';
import useStore from '../store/useStore';
import IngestionProgress, { getIngestionStatus, isIngestionActive } from './IngestionProgress';

const RepoList = () => {
  const {
    repos, selectedRepo, setSelectedRepo, reindexRepo, cancelRepoIndexing, renameRepo, deleteRepo,
  } = useStore();
  const [openMenuId, setOpenMenuId] = useState(null);
  const [retryingRepoId, setRetryingRepoId] = useState(null);
  const [stoppingRepoId, setStoppingRepoId] = useState(null);
  const [repositoryActionError, setRepositoryActionError] = useState(null);
  const [dialog, setDialog] = useState(null);
  const [draftName, setDraftName] = useState('');
  const [actionError, setActionError] = useState('');
  const [isSaving, setIsSaving] = useState(false);
  const dialogRef = useRef(null);
  const dialogInvokerRef = useRef(null);
  const isSavingRef = useRef(false);
  const actionGuardRef = useRef(new Set());

  useEffect(() => {
    isSavingRef.current = isSaving;
  }, [isSaving]);

  useEffect(() => {
    if (!dialog) return undefined;
    const previouslyFocused = dialogInvokerRef.current || document.activeElement;
    const focusFirstControl = () => dialogRef.current?.querySelector('input, button:not([disabled])')?.focus();
    focusFirstControl();

    const onKeyDown = (event) => {
      if (event.key === 'Escape') {
        event.preventDefault();
        if (!isSavingRef.current) closeDialog();
        return;
      }
      if (event.key !== 'Tab' || !dialogRef.current) return;
      const focusable = [...dialogRef.current.querySelectorAll('a[href], button:not([disabled]), input:not([disabled]), select:not([disabled]), textarea:not([disabled]), [tabindex]:not([tabindex="-1"])')];
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
  }, [dialog]);

  const closeDialog = () => {
    if (!isSavingRef.current) {
      setDialog(null);
      setActionError('');
    }
  };

  const handleReindex = async (repo) => {
    if (actionGuardRef.current.has(`reindex:${repo.id}`)) return;
    actionGuardRef.current.add(`reindex:${repo.id}`);
    setRetryingRepoId(repo.id);
    setRepositoryActionError(null);
    try {
      await reindexRepo(repo);
    } catch (error) {
      setRepositoryActionError({
        id: repo.id,
        message: error.response?.data?.detail || 'Could not re-index this repository. Please try again.',
      });
    } finally {
      setRetryingRepoId(null);
      actionGuardRef.current.delete(`reindex:${repo.id}`);
    }
  };

  const handleStop = async (repo) => {
    if (actionGuardRef.current.has(`stop:${repo.id}`)) return;
    actionGuardRef.current.add(`stop:${repo.id}`);
    setStoppingRepoId(repo.id);
    setRepositoryActionError(null);
    try {
      await cancelRepoIndexing(repo);
    } catch (error) {
      setRepositoryActionError({
        id: repo.id,
        message: error.response?.data?.detail || 'Could not stop indexing. Please try again.',
      });
    } finally {
      setStoppingRepoId(null);
      actionGuardRef.current.delete(`stop:${repo.id}`);
    }
  };

  const openRename = (repo) => {
    dialogInvokerRef.current = document.activeElement;
    setOpenMenuId(null);
    setActionError('');
    setDraftName(repo.repo_name);
    setDialog({ type: 'rename', repo });
  };

  const openDelete = (repo) => {
    dialogInvokerRef.current = document.activeElement;
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
                        className="rounded-full p-2 text-warm-gray transition-colors hover:bg-warm-canvas hover:text-ink-black"
                        aria-label={`Repository actions for ${repo.repo_name}`}
                        aria-haspopup="menu"
                        aria-expanded={openMenuId === repo.id}
                      >
                        <Ellipsis className="h-5 w-5" aria-hidden="true" />
                      </button>
                      {openMenuId === repo.id && (
                        <div role="menu" className="absolute right-0 top-8 z-10 w-36 border border-sand bg-pure-white py-1 text-sm shadow-lg">
                          <button type="button" role="menuitem" onClick={() => openRename(repo)} className="flex w-full items-center gap-2 px-3 py-2 text-left text-charcoal hover:bg-warm-canvas">
                            <Pencil className="h-3.5 w-3.5" aria-hidden="true" /> Rename
                          </button>
                          <button type="button" role="menuitem" onClick={() => openDelete(repo)} className="flex w-full items-center gap-2 px-3 py-2 text-left text-red-600 hover:bg-red-50">
                            <Trash2 className="h-3.5 w-3.5" aria-hidden="true" /> Delete
                          </button>
                        </div>
                      )}
                    </div>
                  </div>

                  {isActive && <IngestionProgress repo={repo} compact />}
                  {repo.eligible_files > 0 && (() => {
                    const indexed = repo.indexed_files || 0;
                    const percent = Math.round((indexed / repo.eligible_files) * 100);
                    return (
                      <p className="mt-2 text-xs leading-relaxed text-warm-gray">
                        Indexed {percent}% of eligible source ({indexed}/{repo.eligible_files} files)
                        {repo.excluded_files ? ` · ${repo.excluded_files} omitted by policy` : ''}
                      </p>
                    );
                  })()}
                  {repo.excluded_reasons && Object.keys(repo.excluded_reasons).length > 0 && (
                    <details className="mt-1 text-xs text-warm-gray">
                      <summary className="cursor-pointer hover:text-charcoal">Why files were omitted</summary>
                      <p className="mt-1 leading-relaxed">
                        {Object.entries(repo.excluded_reasons).map(([reason, count]) => `${reason.replaceAll('_', ' ')}: ${count}`).join(' · ')}
                      </p>
                      {repo.excluded_paths?.length > 0 && (
                        <p className="mt-1 max-h-24 overflow-y-auto break-all text-warm-gray">
                          {repo.excluded_paths.join(' · ')}
                        </p>
                      )}
                    </details>
                  )}
                  {repo.error_message && !isActive && (
                    <p className={`mt-3 border-l pl-3 text-xs leading-relaxed ${isCancelled ? 'border-sand text-pewter' : isReady ? 'border-amber-300 text-pewter' : 'border-red-300 text-red-600'}`}>{repo.error_message}</p>
                  )}

                  <div className="mt-4 flex flex-wrap items-center gap-x-4 gap-y-2 text-sm font-semibold">
                      {isReady && (
                      <button type="button" onClick={() => setSelectedRepo(repo.repo_name)} className="inline-flex items-center gap-1.5 text-ink-black transition-colors hover:text-ember-orange">
                        Open chat
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
                    {repositoryActionError?.id === repo.id && (
                      <p className="mt-3 text-xs leading-relaxed text-red-700" role="alert">{repositoryActionError.message}</p>
                    )}
                </div>
              </div>
            </article>
          );
        })}
      </div>

      {dialog && (
        <div className="fixed inset-0 z-[60] grid place-items-center bg-ink-black/20 p-5" role="presentation" onMouseDown={closeDialog}>
          <section ref={dialogRef} className="w-full max-w-sm border border-sand bg-pure-white p-5 shadow-xl" role="dialog" aria-modal="true" aria-labelledby="repository-dialog-title" onMouseDown={(event) => event.stopPropagation()}>
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
                <input id="repository-name" autoFocus value={draftName} maxLength={200} autoComplete="off" onChange={(event) => setDraftName(event.target.value)} className="h-11 w-full border border-sand bg-warm-canvas px-3 text-sm text-ink-black outline-none focus:border-stone" />
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
