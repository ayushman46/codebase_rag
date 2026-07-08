import React from 'react';
import useStore from '../store/useStore';

const RepoList = () => {
  const { repos, selectedRepo, setSelectedRepo } = useStore();

  if (repos.length === 0) {
    return <div className="text-pewter text-sm mt-4">No repositories indexed yet.</div>;
  }

  return (
    <div className="space-y-3">
      {repos.map(repo => {
        const isSelected = selectedRepo === repo.repo_name;
        
        let statusBadge = "bg-stone text-pure-white";
        if (repo.status === 'ready') statusBadge = "bg-ember-orange text-pure-white";
        else if (repo.status === 'failed') statusBadge = "bg-red-500 text-pure-white";
        
        return (
          <div 
            key={repo.id}
            onClick={() => repo.status === 'ready' && setSelectedRepo(repo.repo_name)}
            className={`p-4 rounded-xl border cursor-pointer transition-colors ${isSelected ? 'border-charcoal bg-pure-white' : 'border-sand bg-transparent hover:border-driftwood'} ${repo.status !== 'ready' ? 'opacity-60 cursor-not-allowed' : ''}`}
          >
            <div className="font-medium text-ink-black truncate">{repo.repo_name}</div>
            <div className="mt-3 flex items-center justify-between text-xs">
              <span className={`px-2 py-1 rounded-[6px] font-medium tracking-caption ${statusBadge}`}>
                {repo.status.toUpperCase()}
              </span>
              <span className="text-warm-gray">{repo.chunk_count || 0} chunks</span>
            </div>
            {repo.error_message && (
              <div className="mt-3 text-xs text-red-500 truncate" title={repo.error_message}>
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
