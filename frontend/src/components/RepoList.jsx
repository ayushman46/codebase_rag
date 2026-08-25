import useStore from '../store/useStore';
import IngestionProgress, { getIngestionStatus, isIngestionActive } from './IngestionProgress';

const RepoList = () => {
  const { repos, selectedRepo, setSelectedRepo } = useStore();

  if (repos.length === 0) {
    return <p className="mt-4 text-sm leading-relaxed text-pewter">No codebases indexed yet.</p>;
  }

  return (
    <div className="divide-y divide-sand border-y border-sand">
      {repos.map(repo => {
        const isSelected = selectedRepo === repo.repo_name;
        const isReady = repo.status === 'ready';
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
