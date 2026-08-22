import React, { useState } from 'react';
import { ArrowRight, Loader2 } from 'lucide-react';
import { ingestRepo } from '../api/client';
import useStore from '../store/useStore';

const RepoInput = () => {
  const [url, setUrl] = useState('');
  const { isIngesting, setIngesting, fetchRepos } = useStore();

  const handleSubmit = async (e) => {
    e.preventDefault();
    if (!url) return;
    setIngesting(true);
    try {
      await ingestRepo(url);
      setUrl('');
      await fetchRepos();
    } catch (err) {
      alert("Failed to start ingestion");
    } finally {
      setIngesting(false);
    }
  };

  return (
    <form onSubmit={handleSubmit} className="relative flex items-center w-full">
      <input
        type="url"
        value={url}
        onChange={(e) => setUrl(e.target.value)}
        placeholder="Paste repository GitHub URL..."
        className="w-full h-14 pl-6 pr-16 bg-pure-white border border-sand rounded-[20px] text-body text-ink-black focus:outline-none focus:border-stone placeholder-stone"
        disabled={isIngesting}
      />
      <button
        type="submit"
        disabled={isIngesting || !url}
        className="absolute right-2 w-10 h-10 bg-ember-orange hover:bg-burnt-rust text-pure-white rounded-full flex items-center justify-center transition-colors disabled:opacity-50"
      >
        {isIngesting ? <Loader2 className="w-5 h-5 animate-spin" /> : <ArrowRight className="w-5 h-5" />}
      </button>
    </form>
  );
};

export default RepoInput;
