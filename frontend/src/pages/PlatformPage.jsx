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
    <main className="mx-auto max-w-6xl px-5 py-16 sm:px-8">
      <span className="text-caption font-semibold uppercase tracking-widest text-ember-orange">The platform</span>
      <div className="mt-5 grid gap-10 lg:grid-cols-[1fr_.75fr] lg:items-end">
        <div>
          <h1 className="heading-lg text-heading-lg text-ink-black">A focused workspace for understanding unfamiliar systems.</h1>
          <p className="mt-6 max-w-2xl text-lg leading-relaxed text-pewter">Codebase Intel keeps exploration deliberate: ingest a repository, retrieve relevant evidence, and answer in the context of the code—not assumptions.</p>
        </div>
        <Link to={user ? '/app' : '/'} className="outline-button justify-self-start text-sm">{user ? 'Open workspace' : 'Sign in to begin'}</Link>
      </div>
      <div className="mt-14 grid gap-5 md:grid-cols-2">
        {capabilities.map(({ icon: Icon, title, text }) => (
          <article key={title} className="rounded-[28px] border border-sand bg-pure-white p-7 transition hover:-translate-y-1 hover:shadow-[0_14px_40px_rgba(48,38,31,0.08)]">
            <Icon className="h-6 w-6 text-ember-orange" />
            <h2 className="mt-8 text-heading-sm font-semibold text-ink-black">{title}</h2>
            <p className="mt-3 max-w-md leading-relaxed text-pewter">{text}</p>
          </article>
        ))}
      </div>
    </main>
  );
};

export default PlatformPage;
