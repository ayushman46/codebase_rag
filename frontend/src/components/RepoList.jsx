import useStore from '../store/useStore';
import IngestionProgress, { getIngestionStatus } from './IngestionProgress';

const RepoList = () => {
  const { repos, selectedRepo, setSelectedRepo } = useStore();

  if (repos.length === 0) {
    return <div className="text-pewter text-sm mt-4">No repositories indexed yet.</div>;
  }

  return (
    <div className="space-y-3">
      {repos.map(repo => {
        const isSelected = selectedRepo === repo.repo_name;
        const isReady = repo.status === 'ready';
        const status = getIngestionStatus(repo.status);
        
        return (
          <div 
            key={repo.id}
            onClick={() => isReady && setSelectedRepo(repo.repo_name)}
            className={`rounded-xl border p-4 transition-colors ${isSelected ? 'border-charcoal bg-pure-white' : 'border-sand bg-transparent'} ${isReady ? 'cursor-pointer hover:border-driftwood' : 'cursor-default'}`}
            aria-disabled={!isReady}
          >
            <div className="font-medium text-ink-black truncate">{repo.repo_name}</div>
            <div className="mt-3 flex items-center justify-between text-xs">
              <span className={`rounded-[6px] px-2 py-1 font-medium tracking-caption ${isReady ? 'bg-emerald-600 text-pure-white' : repo.status === 'failed' ? 'bg-red-500 text-pure-white' : 'bg-charcoal text-pure-white'}`}>
                {status.label.toUpperCase()}
              </span>
              <span className="text-warm-gray">{repo.chunk_count || 0} chunks</span>
            </div>
            <IngestionProgress repo={repo} compact />
            {repo.error_message && (
              <div className="mt-3 text-xs leading-relaxed text-red-600" title={repo.error_message}>
                {repo.error_message}
              </div>
            )}
          </div>
        );
      })}
    </div>
  );
};

export default RepoList;
