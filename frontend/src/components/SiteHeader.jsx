import { Menu } from 'lucide-react';
import { useState } from 'react';
import { Link, NavLink } from 'react-router-dom';
import useStore from '../store/useStore';
import GoogleSignInButton from './GoogleSignInButton';

const navClass = ({ isActive }) => (
  `text-[15px] font-medium transition-colors ${isActive ? 'text-ink-black' : 'text-warm-gray hover:text-ink-black'}`
);

const SiteHeader = ({ onOpenRepos }) => {
  const { user } = useStore();
  const displayName = user?.user_metadata?.full_name || user?.email?.split('@')[0] || 'Account';
  const [mobileMenuOpen, setMobileMenuOpen] = useState(false);

  return (
    <header className="sticky top-0 z-40 border-b border-sand/80 bg-warm-canvas/95 backdrop-blur">
      <nav className="content-shell relative flex min-h-[4.75rem] items-center justify-between sm:min-h-[5.25rem]">
        <Link to="/" className="shrink-0 text-lg font-semibold tracking-tight text-ink-black">
          Codebase Intel
        </Link>

        <div className="absolute left-1/2 hidden -translate-x-1/2 items-center gap-10 md:flex">
          {user && onOpenRepos && (
            <button onClick={onOpenRepos} className="text-[15px] font-medium text-warm-gray transition-colors hover:text-ink-black">Codebases</button>
          )}
          <NavLink to="/platform" className={navClass}>Platform</NavLink>
          <NavLink to="/pricing" className={navClass}>Pricing</NavLink>
          <NavLink to="/docs" className={navClass}>Docs</NavLink>
        </div>

        <div className="ml-auto flex shrink-0 items-center gap-3">
          <button onClick={() => setMobileMenuOpen((open) => !open)} className="p-1 text-warm-gray transition hover:text-ink-black md:hidden" aria-label="Toggle navigation" aria-expanded={mobileMenuOpen}><Menu className="h-5 w-5" /></button>
          {user ? (
            <Link to="/account" className="flex h-9 w-9 items-center justify-center rounded-full transition-opacity hover:opacity-75" aria-label="Open account">
              {user.user_metadata?.avatar_url ? (
                <img src={user.user_metadata.avatar_url} alt="" className="h-9 w-9 rounded-full border border-sand" referrerPolicy="no-referrer" />
              ) : (
                <span className="flex h-9 w-9 items-center justify-center rounded-full bg-peach-blush text-[11px] font-bold uppercase text-burnt-rust">
                  {displayName.slice(0, 2)}
                </span>
              )}
            </Link>
          ) : (
            <GoogleSignInButton compact />
          )}
        </div>
      </nav>
      {mobileMenuOpen && (
        <div className="absolute inset-x-0 top-full z-30 border-b border-sand bg-warm-canvas py-4 md:hidden">
          <div className="content-shell flex flex-col gap-5 text-[15px] font-medium">
            {user && onOpenRepos && <button onClick={() => { setMobileMenuOpen(false); onOpenRepos(); }} className="text-left text-charcoal">Codebases</button>}
            <NavLink onClick={() => setMobileMenuOpen(false)} to="/platform" className={navClass}>Platform</NavLink>
            <NavLink onClick={() => setMobileMenuOpen(false)} to="/pricing" className={navClass}>Pricing</NavLink>
            <NavLink onClick={() => setMobileMenuOpen(false)} to="/docs" className={navClass}>Docs</NavLink>
          </div>
        </div>
      )}
    </header>
  );
};

export default SiteHeader;
