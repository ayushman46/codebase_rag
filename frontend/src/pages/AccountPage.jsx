import { CalendarDays, LogOut, Mail, ShieldCheck } from 'lucide-react';
import useStore from '../store/useStore';

const AccountPage = () => {
  const { repos, signOut, user } = useStore();
  const fullName = user?.user_metadata?.full_name || user?.email?.split('@')[0] || 'Workspace member';
  const createdAt = user?.created_at ? new Date(user.created_at).toLocaleDateString(undefined, { month: 'long', year: 'numeric' }) : 'Recently';

  return (
    <main className="narrow-shell page-section">
      <span className="text-caption font-semibold uppercase tracking-widest text-ember-orange">Account</span>
      <div className="mt-5 flex flex-col justify-between gap-8 sm:flex-row sm:items-end">
        <div><h1 className="heading-lg page-title text-ink-black">Your workspace</h1><p className="mt-4 max-w-2xl text-lg text-pewter">Manage the identity connected to your repository intelligence workspace.</p></div>
        <button onClick={signOut} className="outline-button inline-flex w-fit items-center gap-2 text-sm"><LogOut className="h-4 w-4" /> Sign out</button>
      </div>

      <section className="mt-10 rounded-[32px] border border-sand bg-pure-white p-7 sm:mt-12 sm:p-9">
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
