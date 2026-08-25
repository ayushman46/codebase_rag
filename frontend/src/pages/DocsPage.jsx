import { Link } from 'react-router-dom';
import useStore from '../store/useStore';

const flow = [
  {
    step: '01',
    title: 'Create a workspace',
    text: 'Google sign-in establishes an account-scoped workspace. Your repositories, conversations, and access remain associated with the signed-in account.',
  },
  {
    step: '02',
    title: 'Index the source',
    text: 'Paste a public GitHub repository URL. Codebase Intel validates and shallow-clones the repository, filters unsupported files, and preserves file paths, symbols, and line ranges while preparing the index.',
  },
  {
    step: '03',
    title: 'Ask with evidence',
    text: 'Choose a ready repository and ask about architecture, implementation, dependencies, or data flow. Relevant source is retrieved before the answer is generated, with citations that lead back to the code.',
  },
];

const DocsPage = () => {
  const { user } = useStore();

  return (
    <main className="content-shell page-section">
      <article className="mx-auto max-w-4xl">
        <header className="mx-auto max-w-3xl text-center">
          <p className="text-caption font-semibold uppercase tracking-[0.18em] text-ember-orange">Documentation</p>
          <h1 className="heading-lg page-title mt-5 text-ink-black">A clear path from repository to evidence.</h1>
          <p className="mx-auto mt-6 max-w-2xl text-lg leading-relaxed text-pewter">
            Codebase Intel creates a focused workspace for exploring unfamiliar code. Every answer begins with the repository source, so the explanation stays connected to the implementation.
          </p>
        </header>

        <nav className="mx-auto mt-12 flex max-w-2xl flex-wrap justify-center gap-x-8 gap-y-3 border-y border-sand py-4 text-sm" aria-label="Documentation sections">
          <a href="#getting-started" className="text-warm-gray transition-colors hover:text-ink-black">Getting started</a>
          <a href="#repository-flow" className="text-warm-gray transition-colors hover:text-ink-black">How it works</a>
          <a href="#answers" className="text-warm-gray transition-colors hover:text-ink-black">Answers and access</a>
        </nav>

        <section id="getting-started" className="mx-auto max-w-2xl py-16 text-center sm:py-20">
          <p className="text-caption font-semibold uppercase tracking-[0.18em] text-ember-orange">Getting started</p>
          <h2 className="heading-sm mt-4 text-heading text-ink-black">Begin with a public GitHub URL.</h2>
          <p className="mt-5 leading-relaxed text-pewter">
            Open a workspace, submit a repository, and wait for it to become ready. From there, you can ask focused questions without losing the connection to the underlying source files.
          </p>
          <Link to={user ? '/app' : '/'} className="mt-7 inline-block text-sm font-semibold text-ember-orange transition-colors hover:text-burnt-rust">
            {user ? 'Open your workspace' : 'Sign in to get started'}
          </Link>
        </section>

        <section id="repository-flow" className="border-t border-sand py-16 sm:py-20">
          <div className="mx-auto max-w-2xl text-center">
            <p className="text-caption font-semibold uppercase tracking-[0.18em] text-ember-orange">How it works</p>
            <h2 className="heading-sm mt-4 text-heading text-ink-black">A deliberate repository flow.</h2>
          </div>
          <ol className="mx-auto mt-12 max-w-3xl divide-y divide-sand border-y border-sand">
            {flow.map(({ step, title, text }) => (
              <li key={step} className="grid gap-4 py-8 sm:grid-cols-[4rem_1fr] sm:gap-8 sm:py-10">
                <p className="text-caption font-semibold tracking-[0.18em] text-ember-orange">{step}</p>
                <div>
                  <h3 className="text-xl font-semibold tracking-tight text-ink-black">{title}</h3>
                  <p className="mt-3 max-w-2xl leading-relaxed text-pewter">{text}</p>
                </div>
              </li>
            ))}
          </ol>
        </section>

        <section id="answers" className="mx-auto max-w-2xl border-t border-sand py-16 text-center sm:py-20">
          <p className="text-caption font-semibold uppercase tracking-[0.18em] text-ember-orange">Answers and access</p>
          <h2 className="heading-sm mt-4 text-heading text-ink-black">Exploration stays grounded.</h2>
          <p className="mt-5 leading-relaxed text-pewter">
            Your signed-in identity scopes access to your workspace. When available, semantic and keyword retrieval locate relevant code; when semantic retrieval is temporarily unavailable, keyword evidence keeps the workspace useful. Answers include the files and line ranges that support them.
          </p>
        </section>
      </article>
    </main>
  );
};

export default DocsPage;
