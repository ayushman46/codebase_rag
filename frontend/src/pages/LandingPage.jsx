import { ArrowRight } from 'lucide-react';
import { Link } from 'react-router-dom';
import GoogleSignInButton from '../components/GoogleSignInButton';
import useStore from '../store/useStore';

const LandingPage = () => {
  const { authError, clearAuthError, user } = useStore();

  return (
    <main className="content-shell landing-page page-section">
      <section className="mx-auto flex w-full max-w-3xl flex-col items-center text-center">
        <div className="space-y-6">
          <h1 className="heading-display landing-title text-ink-black">Know the code before you change it.</h1>
          <p className="mx-auto max-w-2xl text-lg leading-relaxed text-pewter">
              Sign in to build a private, source-grounded workspace for every public GitHub repository you investigate.
          </p>
        </div>

        {user ? (
          <Link to="/app" className="mt-8 inline-flex items-center gap-2 px-6 py-3 pill-button text-sm sm:mt-10">
            Open your workspace <ArrowRight className="h-4 w-4" />
          </Link>
        ) : (
          <div className="mt-8 flex w-full max-w-lg flex-col items-center space-y-4 sm:mt-10">
            <GoogleSignInButton className="px-6 py-3" />
            <p className="text-xs text-warm-gray">Google sign-in protects your repositories, history, and workspace.</p>
            {authError && (
              <div className="w-full rounded-2xl border border-red-200 bg-red-50 px-4 py-3 text-left text-sm text-red-700" role="alert">
                <div className="flex items-start justify-between gap-4">
                  <span>{authError}</span>
                  <button onClick={clearAuthError} className="font-semibold underline">Dismiss</button>
                </div>
              </div>
            )}
          </div>
        )}
      </section>
    </main>
  );
};

export default LandingPage;
