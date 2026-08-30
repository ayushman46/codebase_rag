import { Loader2 } from 'lucide-react';
import useStore from '../store/useStore';

const GoogleSignInButton = ({ compact = false, className = '' }) => {
  const { signInWithGoogle, isSigningIn } = useStore();

  return (
    <button
      type="button"
      onClick={signInWithGoogle}
      disabled={isSigningIn}
      className={compact
        ? `inline-flex min-h-11 items-center justify-center text-sm font-medium text-warm-gray transition hover:text-ink-black disabled:cursor-not-allowed disabled:opacity-70 ${className}`
        : `inline-flex items-center justify-center gap-2 rounded-full bg-ink-black px-5 py-2.5 text-sm font-semibold text-pure-white transition hover:bg-charcoal disabled:cursor-not-allowed disabled:opacity-70 ${className}`}
    >
      {!compact && isSigningIn && <Loader2 className="h-4 w-4 animate-spin" />}
      <span>{isSigningIn ? 'Connecting…' : compact ? 'Sign in' : 'Continue with Google'}</span>
    </button>
  );
};

export default GoogleSignInButton;
