import { CalendarDays, Database, LogOut, Mail, ShieldCheck } from 'lucide-react';
import { useEffect, useState } from 'react';
import { Link } from 'react-router-dom';
import { getAccountUsage } from '../api/client';
import useStore from '../store/useStore';

const AccountPage = () => {
  const { repos, signOut, user } = useStore();
  const [usage, setUsage] = useState(null);
  const [usageLoading, setUsageLoading] = useState(true);
  const [usageError, setUsageError] = useState('');
  const fullName = user?.user_metadata?.full_name || user?.email?.split('@')[0] || 'Workspace member';
  const createdAt = user?.created_at ? new Date(user.created_at).toLocaleDateString(undefined, { month: 'long', year: 'numeric' }) : 'Recently';

  useEffect(() => {
    let active = true;
    setUsageLoading(true);
    setUsageError('');
    getAccountUsage()
      .then(({ data }) => {
        if (active) setUsage(data);
      })
      .catch((error) => {
        if (!active) return;
        setUsageError(error.response?.data?.detail || 'Usage information is temporarily unavailable.');
      })
      .finally(() => {
        if (active) setUsageLoading(false);
      });
    return () => { active = false; };
  }, [user?.id]);

  const usagePercent = usage ? Math.min(100, Math.round((usage.used_bytes / Math.max(1, usage.quota_bytes)) * 100)) : 0;

  return (
    <main className="narrow-shell page-section">
      <span className="text-caption font-semibold uppercase tracking-widest text-ember-orange">Account</span>
      <div className="mt-5 flex flex-col justify-between gap-8 sm:flex-row sm:items-end">
        <div><h1 className="heading-lg page-title text-ink-black">Your workspace</h1><p className="mt-4 max-w-2xl text-lg text-pewter">Manage the identity connected to your repository intelligence workspace.</p></div>
        <button onClick={signOut} className="outline-button inline-flex w-fit items-center gap-2 text-sm"><LogOut className="h-4 w-4" /> Sign out</button>
      </div>

      <section className="mt-8 rounded-[32px] border border-sand bg-pure-white p-7 sm:mt-10 sm:p-9" aria-labelledby="indexed-source-heading">
        <div className="flex flex-col gap-4 sm:flex-row sm:items-start sm:justify-between">
          <div>
            <div className="flex items-center gap-2"><Database className="h-4 w-4 text-ember-orange" aria-hidden="true" /><h2 id="indexed-source-heading" className="text-xl font-semibold tracking-tight text-ink-black">Indexed storage</h2></div>
            <p className="mt-2 text-sm leading-relaxed text-pewter">Your cumulative indexed source across repositories.</p>
          </div>
          {usage && <span className="w-fit rounded-full bg-warm-canvas px-3 py-1 text-xs font-semibold uppercase tracking-wider text-warm-gray">{usage.plan === 'team' ? 'Team plan' : 'Explorer plan'}</span>}
        </div>

        {usageLoading ? (
          <p className="mt-7 text-sm text-pewter" role="status">Loading usage…</p>
        ) : usageError ? (
          <p className="mt-7 text-sm leading-relaxed text-red-700" role="alert">{usageError}</p>
        ) : usage ? (
          <div className="mt-7">
            <div className="flex items-baseline justify-between gap-4 text-sm"><p className="font-semibold text-charcoal">{usage.used_label} used</p><p className="text-warm-gray">of {usage.quota_label}</p></div>
            <div className="mt-3 h-2 overflow-hidden rounded-full bg-warm-canvas" role="progressbar" aria-label="Indexed source quota" aria-valuemin="0" aria-valuemax="100" aria-valuenow={usagePercent}>
              <div className={`h-full rounded-full transition-[width] ${usagePercent >= 90 ? 'bg-red-500' : 'bg-ember-orange'}`} style={{ width: `${usagePercent}%` }} />
            </div>
            <div className="mt-3 flex flex-col gap-2 text-sm sm:flex-row sm:items-center sm:justify-between"><p className="text-pewter">{usage.remaining_label} remaining</p>{usage.plan === 'explorer' && <Link to="/pricing" className="font-semibold text-ember-orange hover:text-burnt-rust">Choose Team for ₹300/month</Link>}</div>
          </div>
        ) : null}
      </section>

      <section className="mt-5 rounded-[32px] border border-sand bg-pure-white p-7 sm:p-9">
        <div className="flex flex-col gap-6 sm:flex-row sm:items-center">
          {user?.user_metadata?.avatar_url ? <img src={user.user_metadata.avatar_url} alt="" className="h-20 w-20 rounded-full border border-sand" referrerPolicy="no-referrer" /> : <div className="flex h-20 w-20 items-center justify-center rounded-full bg-peach-blush text-2xl font-bold uppercase text-burnt-rust">{fullName.slice(0, 2)}</div>}
          <div><h2 className="text-2xl font-semibold tracking-tight text-ink-black">{fullName}</h2><p className="mt-1 text-sm text-warm-gray">Google-connected account</p></div>
        </div>
        <div className="mt-9 grid gap-4 border-t border-sand pt-7 sm:grid-cols-3">
          <div className="rounded-2xl bg-warm-canvas p-4"><Mail className="h-4 w-4 text-ember-orange" /><p className="mt-4 text-caption font-semibold uppercase tracking-wider text-warm-gray">Email</p><p className="mt-1 truncate text-sm font-semibold text-charcoal">{user?.email}</p></div>
          <div className="rounded-2xl bg-warm-canvas p-4"><CalendarDays className="h-4 w-4 text-ember-orange" /><p className="mt-4 text-caption font-semibold uppercase tracking-wider text-warm-gray">Member since</p><p className="mt-1 text-sm font-semibold text-charcoal">{createdAt}</p></div>
          <div className="rounded-2xl bg-warm-canvas p-4"><ShieldCheck className="h-4 w-4 text-ember-orange" /><p className="mt-4 text-caption font-semibold uppercase tracking-wider text-warm-gray">Indexed repos</p><p className="mt-1 text-sm font-semibold text-charcoal">{repos.length}</p></div>
        </div>
      </section>
    </main>
  );
};

export default AccountPage;
