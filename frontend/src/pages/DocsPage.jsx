import { Link } from 'react-router-dom';
import useStore from '../store/useStore';

const flow = [
  {
    step: '01',
    title: 'Sign in',
    text: 'Google sign-in establishes an account-scoped workspace. Repository records, conversations, and access remain associated with the signed-in user.',
  },
  {
    step: '02',
    title: 'Index a repository',
    text: 'Paste a public GitHub repository URL. Codebase Intel validates and shallow-clones it, filters unsupported files, preserves file paths and line ranges, then builds a searchable index from the source.',
  },
  {
    step: '03',
    title: 'Ask with context',
    text: 'Choose a ready repository and ask about architecture, implementation, dependencies, or data flow. Semantic and keyword retrieval select relevant code before a grounded answer is generated.',
  },
];

const DocsPage = () => {
  const { user } = useStore();

  return (
    <main className="content-shell page-section">
      <article className="mx-auto max-w-3xl text-center">
        <span className="text-caption font-semibold uppercase tracking-widest text-ember-orange">Documentation</span>
        <h1 className="heading-lg page-title mt-5 text-ink-black">From repository URL to a cited answer.</h1>
        <p className="mx-auto mt-6 max-w-2xl text-lg leading-relaxed text-pewter">
          Codebase Intel is built for deliberate codebase exploration. It turns a public repository into a private workspace where every answer is grounded in retrieved source evidence.
        </p>

        <nav className="mt-8 flex flex-wrap justify-center gap-x-6 gap-y-3 text-sm font-medium" aria-label="Documentation sections">
          <a href="#getting-started" className="text-warm-gray transition-colors hover:text-ink-black">Getting started</a>
          <a href="#repository-flow" className="text-warm-gray transition-colors hover:text-ink-black">Repository flow</a>
          <a href="#privacy" className="text-warm-gray transition-colors hover:text-ink-black">Privacy and access</a>
        </nav>

        <section id="getting-started" className="mt-10">
          <Link to={user ? '/app' : '/'} className="text-sm font-semibold text-ember-orange transition-colors hover:text-burnt-rust">
            {user ? 'Open your workspace' : 'Sign in to get started'}
          </Link>
        </section>

        <section id="repository-flow" className="mt-16">
          <h2 className="heading-sm text-heading text-ink-black">Repository flow</h2>
          <ol className="mt-10 space-y-10">
            {flow.map(({ step, title, text }) => (
              <li key={step}>
                <p className="text-caption font-bold text-ember-orange">{step}</p>
                <h3 className="mt-3 text-heading-sm font-semibold text-ink-black">{title}</h3>
                <p className="mx-auto mt-3 max-w-2xl text-sm leading-relaxed text-pewter">{text}</p>
              </li>
            ))}
          </ol>
        </section>

        <section id="privacy" className="mt-16">
          <h2 className="heading-sm text-heading text-ink-black">Privacy and access</h2>
          <p className="mx-auto mt-5 max-w-2xl leading-relaxed text-pewter">
            Authentication identifies the workspace owner. Repository data and queries are protected by user-scoped access controls, and the workspace remains unavailable until a valid session exists. Answers include the files and line ranges used as supporting evidence, so exploration stays connected to the codebase itself.
          </p>
        </section>
      </article>
    </main>
  );
};

export default DocsPage;
