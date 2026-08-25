import { Loader2, RefreshCw } from 'lucide-react';
import { useState } from 'react';
import { ingestRepo } from '../api/client';
import useStore from '../store/useStore';
import IngestionProgress, { getIngestionStatus, isIngestionActive } from './IngestionProgress';

const RepoList = () => {
  const { repos, selectedRepo, setSelectedRepo, fetchRepos } = useStore();
  const [retryingRepoId, setRetryingRepoId] = useState(null);
  const [retryError, setRetryError] = useState(null);

  const handleReindex = async (repo) => {
    setRetryingRepoId(repo.id);
    setRetryError(null);
    try {
      await ingestRepo(repo.github_url);
      await fetchRepos();
    } catch (error) {
      setRetryError({
        repoId: repo.id,
        message: error.response?.data?.detail || 'Could not queue this repository. Please try again.',
      });
    } finally {
      setRetryingRepoId(null);
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
        const isRetrying = retryingRepoId === repo.id;
        const status = getIngestionStatus(repo.status);
        const stateClass = isReady ? 'text-emerald-700' : repo.status === 'failed' ? 'text-red-600' : 'text-ember-orange';
        const content = (
          <>
            <div className="flex items-start justify-between gap-4">
              <p className="min-w-0 truncate text-base font-semibold tracking-tight text-ink-black">{repo.repo_name}</p>
              <span className="shrink-0 pt-0.5 text-xs text-warm-gray">{repo.chunk_count || 0} chunks</span>
            </div>
            <p className={`mt-2 text-xs font-semibold ${stateClass}`}>{isReady ? 'Ready' : repo.status === 'failed' ? 'Needs attention' : status.label}</p>
            {isIngestionActive(repo.status) && <IngestionProgress repo={repo} compact />}
            {repo.error_message && <p className="mt-3 border-l border-red-300 pl-3 text-xs leading-relaxed text-red-600">{repo.error_message}</p>}
            {repo.status === 'failed' && (
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
            {repo.status === 'failed' && retryError?.repoId === repo.id && <p className="mt-3 text-xs leading-relaxed text-red-600" role="alert">{retryError.message}</p>}
          </>
        );
        
        return (
          isReady ? (
            <button
              key={repo.id}
              type="button"
              onClick={() => setSelectedRepo(repo.repo_name)}
              className={`w-full px-1 py-5 text-left transition-colors hover:bg-warm-canvas/60 ${isSelected ? 'bg-warm-canvas/60' : ''}`}
              aria-current={isSelected ? 'page' : undefined}
            >
              {content}
            </button>
          ) : (
            <div key={repo.id} className="px-1 py-5" aria-disabled="true">
              {content}
            </div>
          )
        );
      })}
    </div>
  );
};

export default RepoList;
