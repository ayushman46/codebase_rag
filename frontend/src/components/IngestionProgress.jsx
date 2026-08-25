import { Check, CircleAlert, Clock3, FileSearch, GitBranch, Loader2, Sparkles } from 'lucide-react';

const stages = [
  { id: 'queued', label: 'Queued', detail: 'Your repository is safely queued and waiting for the next indexing worker.', icon: Clock3 },
  { id: 'cloning', label: 'Cloning', detail: 'Creating a shallow, temporary copy of the public repository.', icon: GitBranch },
  { id: 'chunking', label: 'Reading code', detail: 'Finding supported source files and organizing them into useful code sections.', icon: FileSearch },
  { id: 'embedding', label: 'Indexing', detail: 'Building the semantic index used to retrieve relevant code evidence.', icon: Sparkles },
  { id: 'summarizing', label: 'Mapping', detail: 'Preparing the architecture summary and onboarding context.', icon: Sparkles },
];

const stageIndex = (status) => stages.findIndex((stage) => stage.id === status);

const statusStyles = {
  ready: 'bg-emerald-600 text-white',
  failed: 'bg-red-600 text-white',
  pending: 'bg-charcoal text-white',
};

export const isIngestionActive = (status) => stageIndex(status) >= 0;

export const getIngestionStatus = (status) => {
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
  return index >= 0
    ? { ...stages[index], index }
    : { label: 'Preparing', detail: 'Preparing this repository for indexing.', index: 0 };
};

const IngestionProgress = ({ repo, compact = false }) => {
  const info = getIngestionStatus(repo.status);
  const isReady = repo.status === 'ready';
  const isFailed = repo.status === 'failed';
  const active = isIngestionActive(repo.status);
  const Icon = isReady ? Check : isFailed ? CircleAlert : info.icon || Loader2;
  const progress = isReady ? 100 : isFailed ? 0 : Math.round(((info.index + 1) / stages.length) * 100);

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
          <span className="font-medium text-pewter">{`Step ${info.index + 1} of ${stages.length} · ${info.label}`}</span>
          <span className="text-warm-gray">{progress}%</span>
        </div>
        <div className="h-px overflow-hidden bg-sand" aria-hidden="true">
          <div className="h-full bg-ember-orange transition-[width] duration-500" style={{ width: `${progress}%` }} />
        </div>
      </div>
    );
  }

  return (
    <section className={`rounded-3xl border p-5 text-left shadow-sm ${isFailed ? 'border-red-200 bg-red-50' : isReady ? 'border-emerald-200 bg-emerald-50' : 'border-sand bg-pure-white'}`} aria-live="polite">
      <div className="flex items-start gap-3">
        <div className={`mt-0.5 flex h-9 w-9 shrink-0 items-center justify-center rounded-full ${isFailed ? 'bg-red-100 text-red-600' : isReady ? 'bg-emerald-100 text-emerald-700' : 'bg-ember-orange/10 text-ember-orange'}`}>
          <Icon className={`h-4 w-4 ${active ? 'animate-spin' : ''}`} />
        </div>
        <div className="min-w-0 flex-1">
          <div className="flex flex-wrap items-center justify-between gap-2">
            <p className="font-semibold text-ink-black">{repo.repo_name}</p>
            <span className={`rounded-full px-2.5 py-1 text-caption font-semibold uppercase tracking-wider ${statusStyles[isReady ? 'ready' : isFailed ? 'failed' : 'pending']}`}>{isReady ? 'Ready' : isFailed ? 'Failed' : `Step ${info.index + 1} of ${stages.length}`}</span>
          </div>
          <p className="mt-1 text-sm leading-relaxed text-pewter">{repo.error_message || info.detail}</p>
        </div>
      </div>

      {!isFailed && (
        <>
          <div className="mt-5 h-2 overflow-hidden rounded-full bg-fog" aria-hidden="true">
            <div className={`h-full rounded-full transition-[width] duration-700 ${isReady ? 'bg-emerald-500' : 'bg-ember-orange'}`} style={{ width: `${progress}%` }} />
          </div>
          <ol className="mt-4 grid grid-cols-5 gap-1" aria-label="Indexing progress">
            {stages.map((stage, index) => {
              const complete = isReady || index < info.index;
              const current = !isReady && index === info.index;
              return (
                <li key={stage.id} className="min-w-0 text-center">
                  <div className={`mx-auto flex h-5 w-5 items-center justify-center rounded-full border text-[10px] ${complete ? 'border-ember-orange bg-ember-orange text-white' : current ? 'border-ember-orange bg-peach-blush text-ink-black' : 'border-sand bg-pure-white text-warm-gray'}`}>
                    {complete ? <Check className="h-3 w-3" /> : index + 1}
                  </div>
                  <span className={`mt-1 block truncate text-[10px] ${current ? 'font-semibold text-ink-black' : 'text-warm-gray'}`}>{stage.label}</span>
                </li>
              );
            })}
          </ol>
          {!isReady && <p className="mt-4 text-caption text-warm-gray">Updates automatically every few seconds. Queued work begins when the next indexing worker is available.</p>}
        </>
      )}
    </section>
  );
};

export default IngestionProgress;
