import { Loader2 } from 'lucide-react';
import useStore from '../store/useStore';

const GoogleMark = () => (
  <svg aria-hidden="true" className="h-4 w-4" viewBox="0 0 24 24">
    <path fill="#EA4335" d="M12 10.2v4.1h5.7c-.3 1.3-1.8 3.9-5.7 3.9a6.2 6.2 0 1 1 3.9-11l3-2.9A10.5 10.5 0 1 0 22.5 12c0-.7-.1-1.3-.2-1.8H12Z" />
    <path fill="#4285F4" d="M22.5 12c0-.7-.1-1.3-.2-1.8H12v4.1h5.7c-.3 1.3-1.8 3.9-5.7 3.9v2.7h6.9c2-1.8 3.6-4.6 3.6-8.8Z" />
    <path fill="#FBBC05" d="M6.1 14.2A6.2 6.2 0 0 1 6.1 10V7.3H2.8a10.5 10.5 0 0 0 0 9.4l3.3-2.5Z" />
    <path fill="#34A853" d="M12 20.8c2.8 0 5.1-.9 6.9-2.5L15.5 15a6.2 6.2 0 0 1-9.4-3.3l-3.3 2.5A10.5 10.5 0 0 0 12 20.8Z" />
  </svg>
);

const GoogleSignInButton = ({ compact = false, className = '' }) => {
  const { signInWithGoogle, isSigningIn } = useStore();

  return (
    <button
      type="button"
      onClick={signInWithGoogle}
      disabled={isSigningIn}
      className={`inline-flex items-center justify-center gap-2 rounded-full bg-ink-black px-5 py-2.5 text-sm font-semibold text-pure-white transition hover:bg-charcoal disabled:cursor-not-allowed disabled:opacity-70 ${className}`}
    >
      {isSigningIn ? <Loader2 className="h-4 w-4 animate-spin" /> : <GoogleMark />}
      <span>{isSigningIn ? 'Connecting…' : compact ? 'Sign in' : 'Continue with Google'}</span>
    </button>
  );
};

export default GoogleSignInButton;
