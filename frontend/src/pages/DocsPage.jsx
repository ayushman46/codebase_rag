import { ArrowRight, BookOpen, Github, LockKeyhole, Search } from 'lucide-react';
import { Link } from 'react-router-dom';
import useStore from '../store/useStore';

const sections = [
  { icon: Github, step: '01', title: 'Sign in', text: 'Use Google to create a secure, account-scoped workspace.' },
  { icon: BookOpen, step: '02', title: 'Index a repository', text: 'Paste a public GitHub URL. The platform clones, filters, chunks, and indexes its source.' },
  { icon: Search, step: '03', title: 'Ask with context', text: 'Select a ready repository and ask about architecture, flows, files, or implementation details.' },
];

const DocsPage = () => {
  const { user } = useStore();
  return (
    <main className="content-shell page-section">
      <div className="grid gap-10 lg:grid-cols-[240px_minmax(0,1fr)] lg:gap-12">
        <aside className="border-b border-sand pb-6 lg:sticky lg:top-24 lg:h-fit lg:border-b-0 lg:pb-0">
          <p className="text-caption font-semibold uppercase tracking-widest text-ember-orange">Documentation</p>
          <nav className="mt-5 flex flex-wrap gap-x-5 gap-y-3 text-sm lg:mt-6 lg:block lg:space-y-3 lg:border-l lg:border-sand lg:pl-4">
            <a href="#getting-started" className="block text-charcoal hover:text-ember-orange">Getting started</a>
            <a href="#repository-flow" className="block text-warm-gray hover:text-ember-orange">Repository flow</a>
            <a href="#privacy" className="block text-warm-gray hover:text-ember-orange">Privacy and access</a>
          </nav>
        </aside>
        <article className="max-w-3xl">
          <section id="getting-started">
            <span className="text-caption font-semibold uppercase tracking-widest text-ember-orange">Getting started</span>
            <h1 className="heading-lg mt-5 text-heading-lg text-ink-black">From repository URL to a cited answer.</h1>
            <p className="mt-6 text-lg leading-relaxed text-pewter">Codebase Intel is designed for codebase exploration. The application only unlocks a workspace after Google authentication, keeping repository records isolated to the signed-in user.</p>
            <Link to={user ? '/app' : '/'} className="mt-8 inline-flex items-center gap-2 text-sm font-semibold text-ember-orange hover:text-burnt-rust">{user ? 'Open your workspace' : 'Sign in to get started'} <ArrowRight className="h-4 w-4" /></Link>
          </section>
          <section id="repository-flow" className="mt-14 border-t border-sand pt-10 sm:mt-16 sm:pt-12">
            <h2 className="heading-sm text-heading text-ink-black">Repository flow</h2>
            <div className="mt-8 space-y-5">
              {sections.map(({ icon: Icon, step, title, text }) => (
                <div key={step} className="flex gap-5 rounded-2xl border border-sand bg-pure-white p-5">
                  <span className="text-caption font-bold text-ember-orange">{step}</span>
                  <Icon className="mt-0.5 h-5 w-5 shrink-0 text-ink-black" />
                  <div><h3 className="font-semibold text-ink-black">{title}</h3><p className="mt-1 text-sm leading-relaxed text-pewter">{text}</p></div>
                </div>
              ))}
            </div>
          </section>
          <section id="privacy" className="mt-14 rounded-[28px] bg-ink-black p-7 text-pure-white sm:mt-16 sm:p-8">
            <LockKeyhole className="h-6 w-6 text-peach-blush" />
            <h2 className="heading-sm mt-6 text-heading-sm">Privacy and access</h2>
            <p className="mt-3 max-w-xl leading-relaxed text-fog">Google authentication establishes your account identity. Repository data and queries are retrieved through user-scoped access controls; the workspace is unavailable until a valid session exists.</p>
          </section>
        </article>
      </div>
    </main>
  );
};

export default DocsPage;
