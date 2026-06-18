import React, { useEffect } from 'react';
import { getRepos, getRepoStatus, deleteRepo } from '../api/client';
import useStore from '../store/useStore';

const RepoList = () => {
  const { repos, setRepos, selectedRepo, setSelectedRepo, updateRepoStatus } = useStore();

  const fetchRepos = async () => {
    try {
      const res = await getRepos();
      setRepos(res.data);
    } catch (error) {
      console.error('Failed to fetch repos', error);
    }
  };

  useEffect(() => {
    fetchRepos();
    const interval = setInterval(() => {
      fetchRepos();
    }, 5000);
    return () => clearInterval(interval);
  }, []);

  useEffect(() => {
    // Poll status for all non-ready repos whenever repos list changes
    Object.entries(repos).forEach(([name, data]) => {
      if (data.status !== 'ready' && data.status !== 'error') {
        getRepoStatus(name).then(res => {
          if (JSON.stringify(res.data) !== JSON.stringify(data)) {
            updateRepoStatus(name, res.data);
          }
        }).catch(err => console.error(`Failed to get status for ${name}`, err));
      }
    });
  }, [repos]);

  const handleDelete = async (e, name) => {
    e.stopPropagation();
    if (confirm(`Delete ${name}?`)) {
      await deleteRepo(name);
      fetchRepos();
      if (selectedRepo === name) setSelectedRepo(null);
    }
  };

  return (
    <div className="w-72 bg-slate-900 border-r border-slate-800 flex flex-col h-full">
      <div className="p-6 border-b border-slate-800">
        <h2 className="text-xl font-bold text-white flex items-center space-x-2">
          <span className="text-blue-500">◈</span>
          <span>Repositories</span>
        </h2>
      </div>
      
      <div className="flex-1 overflow-y-auto p-4 space-y-2">
        {Object.entries(repos).map(([name, data]) => (
          <div 
            key={name}
            onClick={() => data.status === 'ready' && setSelectedRepo(name)}
            className={`group relative p-3 rounded-xl cursor-pointer transition-all ${
              selectedRepo === name 
              ? 'bg-blue-600/20 border border-blue-500/50 shadow-[0_0_15px_rgba(59,130,246,0.1)]' 
              : 'hover:bg-slate-800 border border-transparent'
            }`}
          >
            <div className="flex justify-between items-start mb-1">
              <span className={`font-medium truncate ${selectedRepo === name ? 'text-blue-400' : 'text-slate-300'}`}>
                {name}
              </span>
              <button 
                onClick={(e) => handleDelete(e, name)}
                className="opacity-0 group-hover:opacity-100 text-slate-500 hover:text-red-400 transition-opacity"
              >
                ✕
              </button>
            </div>
            
            <div className="flex items-center space-x-2">
              <span className={`text-[10px] px-2 py-0.5 rounded-full font-bold uppercase ${
                data.status === 'ready' ? 'bg-green-500/10 text-green-500' :
                data.status === 'error' ? 'bg-red-500/10 text-red-500' :
                'bg-blue-500/10 text-blue-400 animate-pulse'
              }`}>
                {data.status}
              </span>
              {data.status === 'ready' && (
                <span className="text-[10px] text-slate-500">{data.chunk_count} chunks</span>
              )}
            </div>
          </div>
        ))}
        
        {Object.keys(repos).length === 0 && (
          <div className="text-center py-10 text-slate-500 text-sm italic">
            No repos indexed yet.
          </div>
        )}
      </div>
    </div>
  );
};

export default RepoList;
