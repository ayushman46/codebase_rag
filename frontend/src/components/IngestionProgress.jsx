const stages = [
  { id: 'queued', label: 'Queued', detail: 'Your repository is queued and will begin when the indexing worker is available.' },
  { id: 'cloning', label: 'Cloning', detail: 'Creating a temporary copy of the public repository.' },
  { id: 'chunking', label: 'Reading code', detail: 'Finding source files and organizing them into useful sections.' },
  { id: 'embedding', label: 'Indexing', detail: 'Building the semantic index used to retrieve relevant evidence.' },
  { id: 'summarizing', label: 'Mapping', detail: 'Preparing the repository map and onboarding context.' },
];

const stageIndex = (status) => stages.findIndex((stage) => stage.id === status);

export const isIngestionActive = (status) => stageIndex(status) >= 0;

const parseEmbeddingProgress = (message) => {
  const match = /^Indexing (\d+) of (\d+) code sections \((\d+)%\)\./.exec(message || '');
  if (!match) return null;
  return { completed: Number(match[1]), total: Number(match[2]), percent: Number(match[3]) };
};

export const getIngestionStatus = (status, errorMessage) => {
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
  const isReady = repo.status === 'ready';
  const isFailed = repo.status === 'failed';
  const active = isIngestionActive(repo.status);
  const baseProgress = Math.round(((info.index + 1) / stages.length) * 100);
  const progress = isReady ? 100 : isFailed ? 0 : info.embeddingProgress
    ? Math.round(((info.index + (info.embeddingProgress.percent / 100)) / stages.length) * 100)
    : baseProgress;
  const activeLabel = info.embeddingProgress
    ? `Indexing ${info.embeddingProgress.completed} of ${info.embeddingProgress.total} sections`
    : info.label;

  if (compact) {
    if (isReady) {
      return <p className="mt-2 text-xs font-medium text-emerald-700">Ready to explore</p>;
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
      <p className="mt-4 max-w-2xl text-sm leading-relaxed text-pewter">{repo.error_message || info.detail}</p>

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
