const stages = [
  { id: 'queued', label: 'Queued', detail: 'Your repository is queued and will begin when the indexing worker is available.' },
  { id: 'cloning', label: 'Cloning', detail: 'Creating a temporary copy of the public repository.' },
  { id: 'scanning', label: 'Scanning files', detail: 'Applying the source selection policy and recording exclusions.' },
  { id: 'manifesting', label: 'Comparing changes', detail: 'Hashing source files so unchanged paths can be skipped.' },
  { id: 'chunking', label: 'Reading code', detail: 'Finding source files and organizing them into useful sections.' },
  { id: 'keyword', label: 'Building search', detail: 'Writing keyword searchable chunks before semantic indexing.' },
  { id: 'embedding', label: 'Semantic indexing', detail: 'Building the semantic index used to retrieve relevant evidence.' },
  { id: 'finalizing', label: 'Finalizing', detail: 'Publishing coverage and durable progress metadata.' },
];

const stageIndex = (status) => stages.findIndex((stage) => stage.id === status);

export const isIngestionActive = (status) => status === 'searchable' || stageIndex(status) >= 0;

const parseEmbeddingProgress = (message) => {
  const match = /^Indexing (\d+) of (\d+) code sections \((\d+)%\)\./.exec(message || '');
  if (!match) return null;
  return { completed: Number(match[1]), total: Number(match[2]), percent: Number(match[3]) };
};

export const getIngestionStatus = (status, errorMessage) => {
  if (status === 'searchable') {
    return {
      label: 'Ready to explore',
      detail: 'Keyword search is available now. Semantic indexing is continuing in the background.',
      index: stages.length - 1,
      embeddingProgress: null,
    };
  }
  if (status === 'ready') {
    return { label: 'Ready to explore', detail: 'Indexing is complete. You can now ask questions about this codebase.', index: stages.length };
  }
  if (status === 'failed') {
    return { label: 'Needs attention', detail: 'Indexing stopped before the repository was ready.', index: -1 };
  }
  if (status === 'cancelled') {
    return { label: 'Stopped', detail: 'Indexing was stopped before the repository was ready.', index: -1 };
  }
  const index = stageIndex(status);
  const embeddingProgress = status === 'embedding' ? parseEmbeddingProgress(errorMessage) : null;
  return index >= 0
    ? { ...stages[index], index, embeddingProgress }
    : { label: 'Preparing', detail: 'Preparing this repository for indexing.', index: 0 };
};

const IngestionProgress = ({ repo, compact = false }) => {
  const info = getIngestionStatus(repo.status, repo.error_message);
  const isSearchable = repo.status === 'searchable';
  const isReady = repo.status === 'ready' || isSearchable;
  const isFailed = repo.status === 'failed';
  const active = isIngestionActive(repo.status);
  const baseProgress = Math.round(((info.index + 1) / stages.length) * 100);
  const semanticProgress = Number.isFinite(Number(repo.semantic_progress)) ? Number(repo.semantic_progress) : 0;
  const progress = isSearchable ? Math.max(92, Math.min(99, semanticProgress)) : isReady ? 100 : isFailed ? 0 : info.embeddingProgress
    ? Math.round(((info.index + (info.embeddingProgress.percent / 100)) / stages.length) * 100)
    : baseProgress;
  const activeLabel = isSearchable
    ? `Semantic indexing ${semanticProgress}%`
    : info.embeddingProgress
    ? `Indexing ${info.embeddingProgress.completed} of ${info.embeddingProgress.total} sections`
    : info.label;

  if (compact) {
    if (isReady && !isSearchable) {
      return <p className="mt-2 text-xs font-medium text-emerald-700">{isSearchable ? `Ready to explore · semantic indexing ${semanticProgress}%` : 'Ready to explore'}</p>;
    }

    if (isFailed) {
      return <p className="mt-2 text-xs font-medium text-red-600">Indexing stopped</p>;
    }

    return (
      <div className="mt-3" aria-label={`Ingestion status: ${info.label}`}>
        <div className="mb-2 flex items-center justify-between gap-3 text-caption">
          <span className="font-medium text-pewter">{`Step ${info.index + 1} of ${stages.length} · ${activeLabel}`}</span>
          <span className="text-warm-gray">{info.embeddingProgress ? `${info.embeddingProgress.percent}% of indexing` : `${progress}%`}</span>
        </div>
        <div className="h-px overflow-hidden bg-sand" aria-hidden="true">
          <div className="h-full bg-ember-orange transition-[width] duration-500" style={{ width: `${progress}%` }} />
        </div>
      </div>
    );
  }

  return (
    <section className={`border px-6 py-5 text-left shadow-sm sm:px-7 ${isFailed ? 'border-red-200 bg-red-50' : isReady ? 'border-emerald-200 bg-emerald-50' : 'border-sand bg-pure-white'}`} aria-live="polite">
      <div className="flex flex-wrap items-baseline justify-between gap-x-6 gap-y-2">
        <div>
          <p className="text-lg font-semibold tracking-tight text-ink-black">{repo.repo_name}</p>
          <p className={`mt-1 text-xs font-semibold ${isFailed ? 'text-red-600' : isReady ? 'text-emerald-700' : 'text-ember-orange'}`}>{isReady ? 'Ready to explore' : isFailed ? 'Needs attention' : info.label}</p>
        </div>
        <span className="text-caption font-semibold uppercase tracking-wider text-warm-gray">{isReady ? 'Complete' : isFailed ? 'Stopped' : info.embeddingProgress ? `${info.embeddingProgress.percent}% indexed` : `Step ${info.index + 1} of ${stages.length}`}</span>
      </div>
      <p className="mt-4 max-w-2xl text-sm leading-relaxed text-pewter">{isSearchable ? info.detail : repo.error_message || info.detail}</p>
      {repo.eligible_files > 0 && (
        <p className="mt-2 text-xs leading-relaxed text-warm-gray">
          {isReady
            ? `Indexed ${Math.round(((repo.indexed_files || 0) / repo.eligible_files) * 100)}% of eligible source (${repo.indexed_files || 0}/${repo.eligible_files} files)`
            : `Eligible source files: ${repo.eligible_files}`}
          {repo.excluded_files ? ` · ${repo.excluded_files} omitted by policy` : ''}
        </p>
      )}

      {!isFailed && (
        <>
          <div className="mt-5 h-1 overflow-hidden bg-fog" aria-hidden="true">
            <div className={`h-full transition-[width] duration-700 ${isReady ? 'bg-emerald-500' : 'bg-ember-orange'}`} style={{ width: `${progress}%` }} />
          </div>
          <div className="mt-3 flex flex-wrap items-center justify-between gap-2 text-caption text-warm-gray">
            <span>{activeLabel}</span>
            <span>{progress}%</span>
          </div>
          {!isReady && <p className="mt-4 text-caption text-warm-gray">This progress updates automatically while the repository is being indexed.</p>}
        </>
      )}
    </section>
  );
};

export default IngestionProgress;
