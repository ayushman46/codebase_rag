import { Link } from 'react-router-dom';
import useStore from '../store/useStore';

const sections = [
  ['introduction', 'Introduction'],
  ['workspace', 'Workspace'],
  ['indexing', 'Indexing'],
  ['answers', 'Answers'],
  ['access', 'Access and privacy'],
];

const workflow = [
  ['01', 'Submit a repository', 'Paste a public GitHub repository URL. The service validates the URL and creates a workspace record for the signed-in account.'],
  ['02', 'Read the source', 'The repository is shallow-cloned, unsupported or generated files are skipped, and supported files are divided into source-aware sections with paths, symbols, and line ranges.'],
  ['03', 'Build retrieval', 'When NVIDIA embeddings are available, each source section is added to a semantic index. Keyword retrieval is also prepared, so the workspace can remain useful if semantic indexing is temporarily unavailable.'],
  ['04', 'Ask with context', 'A question retrieves a small set of relevant source sections. The answer is generated from that evidence and paired with the file paths and line ranges used to support it.'],
];

const AnchorList = ({ className = '' }) => (
  <nav className={className} aria-label="Documentation navigation">
    {sections.map(([id, label]) => (
      <a key={id} href={`#${id}`} className="transition-colors hover:text-ink-black">{label}</a>
    ))}
  </nav>
);

const DocsPage = () => {
  const { user } = useStore();

  return (
    <main className="content-shell page-section">
      <div className="mx-auto grid max-w-6xl gap-12 lg:grid-cols-[11rem_minmax(0,1fr)_10rem] lg:gap-12">
        <aside className="hidden lg:block">
          <div className="sticky top-24">
            <p className="text-caption font-semibold uppercase tracking-[0.18em] text-ember-orange">Guide</p>
            <AnchorList className="mt-5 flex flex-col gap-3 text-sm leading-relaxed text-warm-gray" />
          </div>
        </aside>

        <article className="min-w-0">
          <header id="introduction" className="scroll-mt-28">
            <p className="text-caption font-semibold uppercase tracking-[0.18em] text-ember-orange">Documentation</p>
            <h1 className="heading-lg mt-5 text-[clamp(2.7rem,5vw,4.2rem)] text-ink-black">Understand the code before you change it.</h1>
            <p className="mt-7 max-w-2xl text-lg leading-relaxed text-pewter">
              Codebase Intel turns a public repository into a private, source-grounded workspace. It helps you trace unfamiliar systems through concise answers that remain connected to the implementation.
            </p>
            <AnchorList className="mt-10 flex flex-wrap gap-x-6 gap-y-3 border-y border-sand py-4 text-sm text-warm-gray lg:hidden" />
          </header>

          <section id="workspace" className="scroll-mt-28 border-t border-sand pt-14 sm:pt-20">
            <p className="text-caption font-semibold uppercase tracking-[0.18em] text-ember-orange">Workspace</p>
            <h2 className="heading-sm mt-4 text-heading text-ink-black">One repository, one focused place to explore.</h2>
            <div className="mt-6 space-y-5 text-[17px] leading-relaxed text-pewter">
              <p>
                Google sign-in creates an account-scoped workspace. Your repository records, conversation history, and access are associated with that account rather than shared across users.
              </p>
              <p>
                Once a repository is ready, its workspace keeps the conversation and its citations together. This makes it easy to return to a codebase without rebuilding context from the beginning.
              </p>
            </div>
            <Link to={user ? '/app' : '/'} className="mt-8 inline-block text-sm font-semibold text-ember-orange transition-colors hover:text-burnt-rust">
              {user ? 'Open your workspace' : 'Sign in to get started'}
            </Link>
          </section>

          <section id="indexing" className="scroll-mt-28 border-t border-sand pt-14 sm:pt-20">
            <p className="text-caption font-semibold uppercase tracking-[0.18em] text-ember-orange">Indexing</p>
            <h2 className="heading-sm mt-4 text-heading text-ink-black">From a URL to searchable source evidence.</h2>
            <ol className="mt-10 divide-y divide-sand border-y border-sand">
              {workflow.map(([step, title, text]) => (
                <li key={step} className="grid gap-4 py-8 sm:grid-cols-[3.5rem_minmax(0,1fr)] sm:gap-6 sm:py-10">
                  <p className="text-caption font-semibold tracking-[0.18em] text-ember-orange">{step}</p>
                  <div>
                    <h3 className="text-xl font-semibold tracking-tight text-ink-black">{title}</h3>
                    <p className="mt-3 text-[17px] leading-relaxed text-pewter">{text}</p>
                  </div>
                </li>
              ))}
            </ol>
          </section>

          <section id="answers" className="scroll-mt-28 border-t border-sand pt-14 sm:pt-20">
            <p className="text-caption font-semibold uppercase tracking-[0.18em] text-ember-orange">Answers</p>
            <h2 className="heading-sm mt-4 text-heading text-ink-black">Answers begin with evidence, not assumptions.</h2>
            <div className="mt-6 space-y-5 text-[17px] leading-relaxed text-pewter">
              <p>
                For each question, Codebase Intel combines semantic similarity and keyword search to select relevant source sections. The language model receives only that bounded evidence, not the entire repository.
              </p>
              <p>
                Each response includes citations to the files and line ranges it uses. If live answer generation is temporarily unavailable, the workspace still returns the retrieved source context so investigation can continue.
              </p>
            </div>
          </section>

          <section id="access" className="scroll-mt-28 border-t border-sand py-14 sm:py-20">
            <p className="text-caption font-semibold uppercase tracking-[0.18em] text-ember-orange">Access and privacy</p>
            <h2 className="heading-sm mt-4 text-heading text-ink-black">Your workspace remains account-scoped.</h2>
            <p className="mt-6 text-[17px] leading-relaxed text-pewter">
              Authentication establishes the workspace owner, and repository records are protected with user-scoped access controls. Codebase Intel accepts public GitHub repositories; access to indexed records and saved conversations is limited to the signed-in workspace owner.
            </p>
          </section>
        </article>

        <aside className="hidden lg:block">
          <div className="sticky top-24 border-l border-sand pl-5">
            <p className="text-caption font-semibold uppercase tracking-[0.18em] text-stone">On this page</p>
            <AnchorList className="mt-5 flex flex-col gap-3 text-sm leading-relaxed text-warm-gray" />
          </div>
        </aside>
      </div>
    </main>
  );
};

export default DocsPage;
