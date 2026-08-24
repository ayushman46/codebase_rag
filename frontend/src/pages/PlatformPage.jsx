import { Bot, Braces, Database, ShieldCheck } from 'lucide-react';
import { Link } from 'react-router-dom';
import useStore from '../store/useStore';

const capabilities = [
  { icon: Braces, title: 'Repository intelligence', text: 'Turn source files, symbols, and line ranges into a searchable knowledge base.' },
  { icon: Database, title: 'Hybrid retrieval', text: 'Combine semantic and keyword search to find evidence before every answer.' },
  { icon: Bot, title: 'Grounded answers', text: 'Ask architectural questions and receive clear explanations backed by citations.' },
  { icon: ShieldCheck, title: 'Account-scoped access', text: 'Your repository records and queries are tied to your signed-in identity.' },
];

const PlatformPage = () => {
  const { user } = useStore();
  return (
    <main className="content-shell page-section">
      <span className="text-caption font-semibold uppercase tracking-widest text-ember-orange">The platform</span>
      <div className="mt-5 grid gap-8 lg:grid-cols-[1fr_.75fr] lg:items-end lg:gap-12">
        <div>
          <h1 className="heading-lg page-title text-ink-black">A focused workspace for understanding unfamiliar systems.</h1>
          <p className="mt-6 max-w-2xl text-lg leading-relaxed text-pewter">Codebase Intel keeps exploration deliberate: ingest a repository, retrieve relevant evidence, and answer in the context of the code—not assumptions.</p>
        </div>
        <Link to={user ? '/app' : '/'} className="outline-button justify-self-start text-sm">{user ? 'Open workspace' : 'Sign in to begin'}</Link>
      </div>
      <div className="mt-12 border-t border-sand lg:mt-16">
        {capabilities.map(({ icon: Icon, title, text }) => (
          <article key={title} className="grid gap-4 border-b border-sand py-7 sm:grid-cols-[minmax(0,.75fr)_minmax(0,1fr)] sm:items-start sm:gap-10 sm:py-9">
            <div className="flex items-center gap-4">
              <Icon className="h-5 w-5 shrink-0 text-ember-orange" />
              <h2 className="text-heading-sm font-semibold text-ink-black">{title}</h2>
            </div>
            <p className="max-w-xl leading-relaxed text-pewter">{text}</p>
          </article>
        ))}
      </div>
    </main>
  );
};

export default PlatformPage;
