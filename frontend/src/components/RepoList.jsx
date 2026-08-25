import { ArrowUpRight, Loader2, RefreshCw, Square } from 'lucide-react';
import { useState } from 'react';
import useStore from '../store/useStore';
import IngestionProgress, { getIngestionStatus, isIngestionActive } from './IngestionProgress';

const RepoList = () => {
  const { repos, selectedRepo, setSelectedRepo, reindexRepo, cancelRepoIndexing } = useStore();
  const [retryingRepoId, setRetryingRepoId] = useState(null);
  const [retryError, setRetryError] = useState(null);
  const [stoppingRepoId, setStoppingRepoId] = useState(null);
  const [stopError, setStopError] = useState(null);

  const handleReindex = async (repo) => {
    setRetryingRepoId(repo.id);
    setRetryError(null);
    try {
      await reindexRepo(repo);
    } catch (error) {
      setRetryError({
        repoId: repo.id,
        message: error.response?.data?.detail || 'Could not queue this repository. Please try again.',
      });
    } finally {
      setRetryingRepoId(null);
    }
  };

  const handleStop = async (repo) => {
    setStoppingRepoId(repo.id);
    setStopError(null);
    try {
      await cancelRepoIndexing(repo);
    } catch (error) {
      setStopError({
        repoId: repo.id,
        message: error.response?.data?.detail || 'Could not stop repository indexing. Please try again.',
      });
    } finally {
      setStoppingRepoId(null);
    }
  };

  if (repos.length === 0) {
    return <p className="mt-4 text-sm leading-relaxed text-pewter">No codebases indexed yet.</p>;
  }

  return (
    <div className="divide-y divide-sand border-y border-sand">
      {repos.map(repo => {
        const isSelected = selectedRepo === repo.repo_name;
        const isReady = repo.status === 'ready';
        const isCancelled = repo.status === 'cancelled';
        const isActive = isIngestionActive(repo.status);
        const isRetrying = retryingRepoId === repo.id;
        const isStopping = stoppingRepoId === repo.id;
        const status = getIngestionStatus(repo.status, repo.error_message);
        const stateClass = isReady ? 'text-emerald-700' : repo.status === 'failed' ? 'text-red-600' : isCancelled ? 'text-pewter' : 'text-ember-orange';
        const content = (
          <>
            <div className="flex items-start justify-between gap-4">
              <p className="min-w-0 truncate text-base font-semibold tracking-tight text-ink-black">{repo.repo_name}</p>
              <span className="shrink-0 pt-0.5 text-xs text-warm-gray">{repo.chunk_count || 0} chunks</span>
            </div>
            <p className={`mt-2 text-xs font-semibold ${stateClass}`}>{isReady ? 'Ready' : repo.status === 'failed' ? 'Needs attention' : status.label}</p>
            {isActive && <IngestionProgress repo={repo} compact />}
            {repo.error_message && <p className={`mt-3 border-l pl-3 text-xs leading-relaxed ${isActive || isCancelled ? 'border-sand text-pewter' : 'border-red-300 text-red-600'}`}>{repo.error_message}</p>}
            {isReady && (
              <button
                type="button"
                onClick={() => setSelectedRepo(repo.repo_name)}
                className="mt-4 inline-flex items-center gap-2 text-sm font-semibold text-ink-black transition-colors hover:text-ember-orange"
              >
                Open chat <ArrowUpRight className="h-4 w-4" aria-hidden="true" />
              </button>
            )}
            {(repo.status === 'failed' || isCancelled) && (
              <button
                type="button"
                onClick={() => handleReindex(repo)}
                disabled={isRetrying}
                className="mt-4 inline-flex items-center gap-2 text-sm font-semibold text-ember-orange transition-colors hover:text-burnt-rust disabled:cursor-wait disabled:opacity-60"
              >
                {isRetrying ? <Loader2 className="h-4 w-4 animate-spin" aria-hidden="true" /> : <RefreshCw className="h-4 w-4" aria-hidden="true" />}
                {isRetrying ? 'Queueing re-index…' : 'Re-index repository'}
              </button>
            )}
            {isActive && (
              <button
                type="button"
                onClick={() => handleStop(repo)}
                disabled={isStopping}
                className="mt-4 inline-flex items-center gap-2 text-sm font-semibold text-pewter transition-colors hover:text-ink-black disabled:cursor-wait disabled:opacity-60"
              >
                {isStopping ? <Loader2 className="h-4 w-4 animate-spin" aria-hidden="true" /> : <Square className="h-3.5 w-3.5" aria-hidden="true" />}
                {isStopping ? 'Stopping indexing…' : 'Stop indexing'}
              </button>
            )}
            {(repo.status === 'failed' || isCancelled) && retryError?.repoId === repo.id && <p className="mt-3 text-xs leading-relaxed text-red-600" role="alert">{retryError.message}</p>}
            {isActive && stopError?.repoId === repo.id && <p className="mt-3 text-xs leading-relaxed text-red-600" role="alert">{stopError.message}</p>}
          </>
        );
        
        return (
          <div key={repo.id} className={`px-1 py-5 ${isSelected ? 'bg-warm-canvas/60' : ''}`} aria-current={isSelected ? 'page' : undefined}>
            {content}
          </div>
        );
      })}
    </div>
  );
};

export default RepoList;
