import { Link } from 'react-router-dom';
import useStore from '../store/useStore';

const capabilities = [
  {
    number: '01',
    title: 'Repository intelligence',
    text: 'Turn a public GitHub repository into a searchable workspace while keeping source paths, symbols, languages, and line ranges connected to every section of code.',
  },
  {
    number: '02',
    title: 'Evidence-first retrieval',
    text: 'Semantic and keyword retrieval work together to find a focused set of relevant source before an answer is created. The model is not asked to reason over the entire repository at once.',
  },
  {
    number: '03',
    title: 'Cited exploration',
    text: 'Answers return with the files and line ranges that support them, helping you move from a high-level explanation directly into the implementation.',
  },
];

const PlatformPage = () => {
  const { user } = useStore();

  return (
    <main className="content-shell page-section">
      <section className="mx-auto max-w-3xl text-center">
        <p className="text-caption font-semibold uppercase tracking-[0.18em] text-ember-orange">The platform</p>
        <h1 className="heading-lg page-title mt-5 text-ink-black">A focused workspace for understanding unfamiliar systems.</h1>
        <p className="mx-auto mt-7 max-w-2xl text-lg leading-relaxed text-pewter">
          Codebase Intel gives engineering teams a clearer starting point in any public repository. It organizes the source, retrieves relevant evidence, and keeps each explanation tied to the implementation behind it.
        </p>
        <Link to={user ? '/app' : '/'} className="mt-8 inline-block text-sm font-semibold text-ember-orange transition-colors hover:text-burnt-rust">
          {user ? 'Open your workspace' : 'Sign in to explore a repository'}
        </Link>
      </section>

      <section className="mx-auto mt-20 max-w-5xl border-t border-sand pt-14 sm:mt-28 sm:pt-20">
        <div className="grid gap-8 lg:grid-cols-[minmax(0,0.8fr)_minmax(0,1.7fr)] lg:gap-16">
          <div>
            <p className="text-caption font-semibold uppercase tracking-[0.18em] text-ember-orange">What it is for</p>
            <h2 className="heading-sm mt-4 text-heading text-ink-black">Make the first hour in a codebase count.</h2>
          </div>
          <div className="space-y-5 text-[17px] leading-relaxed text-pewter">
            <p>
              The platform is built for the moments when context is missing: joining a project, reviewing an unfamiliar service, tracing a data flow, or preparing a safe change. Instead of relying on assumptions, you can ask questions against retrieved source evidence.
            </p>
            <p>
              A repository becomes a private workspace after indexing. Its conversations are retained with the repository, making it possible to investigate progressively rather than starting over with every question.
            </p>
          </div>
        </div>
      </section>

      <section className="mx-auto mt-20 max-w-5xl border-t border-sand pt-14 sm:mt-28 sm:pt-20">
        <div className="max-w-2xl">
          <p className="text-caption font-semibold uppercase tracking-[0.18em] text-ember-orange">Core capabilities</p>
          <h2 className="heading-sm mt-4 text-heading text-ink-black">The path from source to understanding.</h2>
        </div>
        <ol className="mt-12 divide-y divide-sand border-y border-sand">
          {capabilities.map(({ number, title, text }) => (
            <li key={number} className="grid gap-4 py-8 sm:grid-cols-[4rem_minmax(0,1fr)] sm:gap-8 sm:py-10">
              <p className="text-caption font-semibold tracking-[0.18em] text-ember-orange">{number}</p>
              <div>
                <h3 className="text-xl font-semibold tracking-tight text-ink-black">{title}</h3>
                <p className="mt-3 max-w-3xl text-[17px] leading-relaxed text-pewter">{text}</p>
              </div>
            </li>
          ))}
        </ol>
      </section>

      <section className="mx-auto mt-20 max-w-3xl border-t border-sand py-14 text-center sm:mt-28 sm:py-20">
        <p className="text-caption font-semibold uppercase tracking-[0.18em] text-ember-orange">Built with boundaries</p>
        <h2 className="heading-sm mt-4 text-heading text-ink-black">Relevant context, deliberately scoped.</h2>
        <p className="mt-6 text-[17px] leading-relaxed text-pewter">
          Codebase Intel accepts public repositories and scopes workspace records to the signed-in user. It retrieves a bounded set of relevant source sections for each question, includes citations with answers, and keeps keyword evidence available when semantic retrieval is temporarily unavailable.
        </p>
      </section>
    </main>
  );
};

export default PlatformPage;
