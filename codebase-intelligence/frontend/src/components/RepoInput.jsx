import React, { useState } from 'react';
import { ingestRepo } from '../api/client';
import useStore from '../store/useStore';

const RepoInput = () => {
  const [url, setUrl] = useState('');
  const { setIngesting, isIngesting } = useStore();

  const handleIngest = async (e) => {
    e.preventDefault();
    if (!url) return;
    
    setIngesting(true);
    try {
      await ingestRepo(url);
      setUrl('');
    } catch (error) {
      console.error('Ingestion trigger failed', error);
    } finally {
      setIngesting(false);
    }
  };

  return (
    <form onSubmit={handleIngest} className="mb-8">
      <div className="flex space-x-2">
        <input 
          type="text" 
          value={url}
          onChange={(e) => setUrl(e.target.value)}
          placeholder="https://github.com/username/repo"
          className="flex-1 bg-slate-900 border border-slate-700 rounded-lg px-4 py-2 text-slate-200 focus:outline-none focus:border-blue-500 transition-colors"
        />
        <button 
          type="submit"
          disabled={isIngesting || !url}
          className="bg-blue-600 hover:bg-blue-700 disabled:opacity-50 text-white font-medium px-6 py-2 rounded-lg transition-colors flex items-center space-x-2"
        >
          {isIngesting ? (
            <>
              <div className="animate-spin h-4 w-4 border-2 border-white border-t-transparent rounded-full" />
              <span>Indexing...</span>
            </>
          ) : (
            <span>Index Repo</span>
          )}
        </button>
      </div>
    </form>
  );
};

export default RepoInput;
