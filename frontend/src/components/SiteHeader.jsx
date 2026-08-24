import { LogOut, Menu, Sparkles } from 'lucide-react';
import { useState } from 'react';
import { Link, NavLink } from 'react-router-dom';
import useStore from '../store/useStore';
import GoogleSignInButton from './GoogleSignInButton';

const navClass = ({ isActive }) => (
  `rounded-full px-3 py-1.5 text-sm font-medium transition-colors ${isActive ? 'bg-pure-white text-ink-black shadow-sm ring-1 ring-sand/80' : 'text-warm-gray hover:bg-pure-white hover:text-ink-black'}`
);

const SiteHeader = ({ onOpenRepos }) => {
  const { repos, signOut, user } = useStore();
  const displayName = user?.user_metadata?.full_name || user?.email?.split('@')[0] || 'Account';
  const [mobileMenuOpen, setMobileMenuOpen] = useState(false);

  return (
    <header className="sticky top-0 z-40 border-b border-sand/80 bg-warm-canvas/95 backdrop-blur">
      <nav className="content-shell grid min-h-[4.5rem] grid-cols-[1fr_auto_1fr] items-center gap-3 sm:min-h-20 sm:gap-5">
        <Link to="/" className="flex w-fit shrink-0 items-center gap-2.5">
          <Sparkles className="h-4 w-4 text-ember-orange" aria-hidden="true" />
          <span className="text-base font-semibold tracking-tight text-ink-black">Codebase Intel</span>
        </Link>

        <div className="hidden min-w-0 items-center rounded-full border border-sand/90 bg-warm-canvas/80 p-1 md:flex">
          {user && onOpenRepos && (
            <button onClick={onOpenRepos} className="flex items-center gap-2 rounded-full px-3 py-1.5 text-sm font-medium text-warm-gray transition-colors hover:bg-pure-white hover:text-ink-black">
              Codebases
              <span className="rounded-badges border border-burnt-rust/10 bg-[#fff1ed] px-1.5 py-0.5 text-[10px] font-bold leading-none text-ember-orange">
                {repos.length}
              </span>
            </button>
          )}
          <NavLink to="/platform" className={navClass}>Platform</NavLink>
          <NavLink to="/pricing" className={navClass}>Pricing</NavLink>
          <NavLink to="/docs" className={navClass}>Docs</NavLink>
        </div>

        <div className="flex shrink-0 items-center justify-self-end gap-2 sm:gap-4">
          <button onClick={() => setMobileMenuOpen((open) => !open)} className="rounded-lg p-2 text-warm-gray transition hover:bg-pure-white md:hidden" aria-label="Toggle navigation" aria-expanded={mobileMenuOpen}><Menu className="h-5 w-5" /></button>
          {user ? (
            <>
              <Link to="/account" className="flex items-center gap-2 rounded-full p-1 transition hover:bg-pure-white" aria-label="Open account">
                {user.user_metadata?.avatar_url ? (
                  <img src={user.user_metadata.avatar_url} alt="" className="h-8 w-8 rounded-full border border-sand" referrerPolicy="no-referrer" />
                ) : (
                  <span className="flex h-8 w-8 items-center justify-center rounded-full bg-peach-blush text-xs font-bold uppercase text-burnt-rust">
                    {displayName.slice(0, 2)}
                  </span>
                )}
                <span className="hidden max-w-28 truncate text-xs font-semibold text-charcoal lg:inline">{displayName}</span>
              </Link>
              <button onClick={signOut} className="rounded-lg p-2 text-warm-gray transition hover:bg-pure-white hover:text-ink-black" title="Sign out" aria-label="Sign out">
                <LogOut className="h-4 w-4" />
              </button>
            </>
          ) : (
            <GoogleSignInButton compact />
          )}
        </div>
      </nav>
      {mobileMenuOpen && (
        <div className="absolute inset-x-0 top-full z-30 border-b border-sand bg-pure-white py-4 shadow-lg md:hidden">
          <div className="content-shell flex flex-col gap-1 text-sm font-medium">
            {user && onOpenRepos && <button onClick={() => { setMobileMenuOpen(false); onOpenRepos(); }} className="flex items-center justify-between py-2 text-left text-charcoal">Codebases <span className="rounded-full bg-[#fff1ed] px-2 py-0.5 text-caption text-ember-orange">{repos.length}</span></button>}
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
