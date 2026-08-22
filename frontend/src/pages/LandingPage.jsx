import { ArrowRight, CheckCircle2, LockKeyhole, SearchCode } from 'lucide-react';
import { Link } from 'react-router-dom';
import GoogleSignInButton from '../components/GoogleSignInButton';
import useStore from '../store/useStore';

const LandingPage = () => {
  const { authError, clearAuthError, user } = useStore();

  return (
    <main className="mx-auto flex min-h-[calc(100vh-5rem)] max-w-6xl flex-col justify-center px-5 py-16 sm:px-8">
      <section className="grid items-center gap-12 lg:grid-cols-[1.1fr_.9fr] lg:gap-20">
        <div className="space-y-8">
          <div className="inline-flex items-center gap-2 rounded-full border border-sand bg-pure-white px-3 py-1.5 text-caption font-semibold uppercase tracking-widest text-warm-gray">
            <LockKeyhole className="h-3.5 w-3.5 text-ember-orange" /> Private workspace
          </div>
          <div className="space-y-5">
            <h1 className="heading-display max-w-2xl text-display text-ink-black">Know the code before you change it.</h1>
            <p className="max-w-xl text-lg leading-relaxed text-pewter">
              Sign in to build a private, source-grounded workspace for every public GitHub repository you investigate.
            </p>
          </div>

          {user ? (
            <Link to="/app" className="pill-button inline-flex items-center gap-2 px-6 py-3 text-sm">
              Open your workspace <ArrowRight className="h-4 w-4" />
            </Link>
          ) : (
            <div className="space-y-4">
              <GoogleSignInButton className="px-6 py-3" />
              <p className="text-xs text-warm-gray">Google sign-in protects your repositories, history, and workspace.</p>
              {authError && (
                <div className="max-w-lg rounded-2xl border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-700" role="alert">
                  <div className="flex items-start justify-between gap-4">
                    <span>{authError}</span>
                    <button onClick={clearAuthError} className="font-semibold underline">Dismiss</button>
                  </div>
                </div>
              )}
            </div>
          )}
        </div>

        <div className="rounded-[32px] border border-sand bg-pure-white p-6 shadow-[0_20px_70px_rgba(48,38,31,0.08)] sm:p-8">
          <div className="mb-8 flex items-center justify-between border-b border-sand pb-5">
            <div>
              <p className="text-sm font-semibold text-ink-black">Workspace preview</p>
              <p className="mt-1 text-xs text-warm-gray">Available after Google sign-in</p>
            </div>
            <span className="rounded-full bg-[#fff1ed] px-3 py-1 text-caption font-semibold text-ember-orange">SECURE</span>
          </div>
          <div className="space-y-4">
            {[
              ['Index a repository', 'Source, symbols, and line ranges stay connected.'],
              ['Ask grounded questions', 'Answers cite the code they use.'],
              ['Return with context', 'Your workspace is scoped to your account.'],
            ].map(([title, detail], index) => (
              <div key={title} className="flex gap-4 rounded-2xl bg-warm-canvas p-4">
                <span className="flex h-8 w-8 shrink-0 items-center justify-center rounded-full bg-pure-white text-sm font-semibold text-ember-orange">0{index + 1}</span>
                <div>
                  <p className="text-sm font-semibold text-ink-black">{title}</p>
                  <p className="mt-1 text-sm leading-relaxed text-pewter">{detail}</p>
                </div>
              </div>
            ))}
          </div>
          <div className="mt-6 flex items-center gap-2 text-xs font-medium text-warm-gray"><SearchCode className="h-4 w-4 text-ember-orange" /> Retrieval stays tied to the repository.</div>
        </div>
      </section>

      <section className="mt-20 grid gap-6 border-t border-sand pt-10 sm:grid-cols-3">
        {['Google-backed access', 'Source citations', 'Private workspaces'].map((item) => (
          <div key={item} className="flex items-center gap-2 text-sm font-semibold text-charcoal"><CheckCircle2 className="h-4 w-4 text-ember-orange" />{item}</div>
        ))}
      </section>
    </main>
  );
};

export default LandingPage;
