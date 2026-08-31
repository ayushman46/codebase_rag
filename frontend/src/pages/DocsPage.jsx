import { useState } from 'react';
import { Link } from 'react-router-dom';
import useStore from '../store/useStore';

const guide = [
  {
    id: 'introduction',
    label: 'Introduction',
    eyebrow: 'Documentation',
    title: 'Understand the code before you change it.',
    summary: 'A source-grounded workspace for exploring unfamiliar repositories.',
    paragraphs: [
      'Codebase Intel turns a public GitHub repository into a private workspace for codebase exploration. It is designed to make the first hour in an unfamiliar system more deliberate and less dependent on guesswork.',
      'Rather than treating a repository as a single wall of text, the platform keeps source paths, symbols, and line ranges connected to each answer. This makes it possible to move from an explanation directly to the code that supports it.',
    ],
  },
  {
    id: 'workspace',
    label: 'Workspace',
    eyebrow: 'Workspace',
    title: 'A focused place for each repository.',
    summary: 'Your repositories and conversations stay associated with your account.',
    paragraphs: [
      'Google sign-in establishes an account-scoped workspace. Repository records, saved conversations, and access are associated with the signed-in user rather than shared across the application.',
      'Once a repository is ready, opening its workspace restores the conversation history for that codebase. This lets you return to an investigation without rebuilding the context of earlier questions.',
    ],
    action: true,
  },
  {
    id: 'indexing',
    label: 'Indexing',
    eyebrow: 'Indexing',
    title: 'From a repository URL to searchable source.',
    summary: 'The source is filtered, structured, and prepared for retrieval.',
    paragraphs: [
      'Indexing begins when you submit a public GitHub repository URL. The service validates the repository, creates a shallow clone, and filters files that are unsupported, generated, binary, or too large to be useful evidence.',
      'The workspace reports how many eligible files were indexed and why other files were omitted. Re-indexing compares file hashes and refreshes only changed files, while a conservative local dependency map supports change-impact questions.',
    ],
    steps: [
      ['01', 'Validate and clone', 'The repository URL is checked and a temporary shallow copy is created.'],
      ['02', 'Read and segment code', 'Supported files are divided into source-aware sections while preserving paths, symbols, languages, and line ranges.'],
      ['03', 'Prepare retrieval', 'Keyword retrieval is always prepared. When NVIDIA embeddings are available, a semantic index is created alongside it.'],
      ['04', 'Map the repository', 'A compact metadata map records the files, languages, and symbols available in the workspace.'],
    ],
  },
  {
    id: 'answers',
    label: 'Answers',
    eyebrow: 'Answers',
    title: 'Answers begin with evidence, not assumptions.',
    summary: 'Questions are answered from a bounded selection of relevant source.',
    paragraphs: [
      'For each question, Codebase Intel searches for the most relevant source sections using semantic similarity and keyword search. Only that bounded evidence is passed to answer generation, rather than the entire repository.',
      'Every response includes file and line-range citations plus a short explanation of why each file was selected. Choose a workflow such as security review or onboarding to focus retrieval and answer structure. If a requested claim is not established, the answer identifies that evidence limit instead of guessing.',
    ],
  },
  {
    id: 'access',
    label: 'Access and privacy',
    eyebrow: 'Access and privacy',
    title: 'The workspace remains account-scoped.',
    summary: 'Access is tied to the signed-in workspace owner.',
    paragraphs: [
      'Authentication identifies the workspace owner, and repository records are protected with user-scoped access controls. Codebase Intel accepts public GitHub repositories, while access to indexed records and saved conversations remains limited to the associated account.',
      'Citations keep the exploration process inspectable: an answer can be checked against its supporting source instead of being accepted as an unsupported summary.',
    ],
  },
];

const GuideNavigation = ({ activeId, onSelect, className = '' }) => (
  <nav className={className} aria-label="Documentation navigation">
    {guide.map(({ id, label }) => {
      const active = id === activeId;
      return (
        <button
          key={id}
          type="button"
          onClick={() => onSelect(id)}
          aria-current={active ? 'page' : undefined}
          className={`min-h-11 text-left transition-colors ${active ? 'font-semibold text-ink-black' : 'text-warm-gray hover:text-ink-black'}`}
        >
          {label}
        </button>
      );
    })}
  </nav>
);

const DocsPage = () => {
  const { user } = useStore();
  const [activeId, setActiveId] = useState('introduction');
  const activeSection = guide.find((section) => section.id === activeId) || guide[0];

  return (
    <main className="content-shell page-section">
      <div className="mx-auto grid max-w-6xl gap-12 lg:grid-cols-[11rem_minmax(0,1fr)_10rem] lg:gap-12">
        <aside className="hidden lg:block">
          <div className="sticky top-24">
            <p className="text-caption font-semibold uppercase tracking-[0.18em] text-ember-orange">Guide</p>
            <GuideNavigation activeId={activeId} onSelect={setActiveId} className="mt-5 flex flex-col gap-3 text-sm leading-relaxed" />
          </div>
        </aside>

        <article className="min-w-0" aria-live="polite">
          <GuideNavigation activeId={activeId} onSelect={setActiveId} className="flex gap-x-6 gap-y-3 overflow-x-auto border-y border-sand py-4 text-sm whitespace-nowrap lg:hidden" />

          <section key={activeSection.id} className="pt-12 sm:pt-16">
            <p className="text-caption font-semibold uppercase tracking-[0.18em] text-ember-orange">{activeSection.eyebrow}</p>
            <h1 className="heading-lg mt-5 text-[clamp(2.7rem,5vw,4.2rem)] text-ink-black">{activeSection.title}</h1>
            <p className="mt-6 text-lg leading-relaxed text-pewter">{activeSection.summary}</p>

            <div className="mt-12 space-y-5 border-t border-sand pt-10 text-[17px] leading-relaxed text-pewter">
              {activeSection.paragraphs.map((paragraph) => <p key={paragraph}>{paragraph}</p>)}
            </div>

            {activeSection.steps && (
              <ol className="mt-12 divide-y divide-sand border-y border-sand">
                {activeSection.steps.map(([step, title, text]) => (
                  <li key={step} className="grid gap-4 py-8 sm:grid-cols-[3.5rem_minmax(0,1fr)] sm:gap-6 sm:py-10">
                    <p className="text-caption font-semibold tracking-[0.18em] text-ember-orange">{step}</p>
                    <div>
                      <h2 className="text-xl font-semibold tracking-tight text-ink-black">{title}</h2>
                      <p className="mt-3 text-[17px] leading-relaxed text-pewter">{text}</p>
                    </div>
                  </li>
                ))}
              </ol>
            )}

            {activeSection.action && (
              <Link to={user ? '/app' : '/'} className="mt-10 inline-block text-sm font-semibold text-ember-orange transition-colors hover:text-burnt-rust">
                {user ? 'Open your workspace' : 'Sign in to get started'}
              </Link>
            )}
          </section>
        </article>

        <aside className="hidden lg:block">
          <div className="sticky top-24 border-l border-sand pl-5">
            <p className="text-caption font-semibold uppercase tracking-[0.18em] text-stone">Current section</p>
            <p className="mt-5 text-sm font-semibold text-ink-black">{activeSection.label}</p>
            <p className="mt-3 text-sm leading-relaxed text-warm-gray">{activeSection.summary}</p>
          </div>
        </aside>
      </div>
    </main>
  );
};

export default DocsPage;
