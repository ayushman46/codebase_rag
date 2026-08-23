import { Check } from 'lucide-react';
import { Link } from 'react-router-dom';
import GoogleSignInButton from '../components/GoogleSignInButton';
import useStore from '../store/useStore';

const plans = [
  { name: 'Explorer', price: 'Free', detail: 'For evaluating a repository and learning the workflow.', features: ['Google account workspace', 'Public repository ingestion', 'Grounded answers with citations'], featured: false },
  { name: 'Team', price: 'Coming soon', detail: 'For product teams standardizing codebase discovery.', features: ['Everything in Explorer', 'Shared workspace controls', 'Higher indexing capacity', 'Priority support'], featured: true },
];

const PricingPage = () => {
  const { user } = useStore();
  return (
    <main className="content-shell page-section">
      <div className="mx-auto max-w-2xl text-center">
        <span className="text-caption font-semibold uppercase tracking-widest text-ember-orange">Pricing</span>
        <h1 className="heading-lg page-title mt-5 text-ink-black">Start with a secure personal workspace.</h1>
        <p className="mt-5 text-lg leading-relaxed text-pewter">Simple access today, with team controls planned for growing engineering organizations.</p>
      </div>
      <div className="mx-auto mt-12 grid max-w-4xl gap-6 md:grid-cols-2 lg:mt-16">
        {plans.map((plan) => (
          <article key={plan.name} className={`relative flex min-h-[390px] flex-col rounded-[32px] border p-7 sm:p-8 ${plan.featured ? 'border-ember-orange bg-ink-black text-pure-white shadow-[0_20px_60px_rgba(14,14,15,0.18)]' : 'border-sand bg-pure-white text-ink-black'}`}>
            {plan.featured && <span className="absolute right-6 top-6 rounded-full bg-ember-orange px-3 py-1 text-caption font-bold">PLANNED</span>}
            <p className={`text-sm font-semibold ${plan.featured ? 'text-peach-blush' : 'text-ember-orange'}`}>{plan.name}</p>
            <h2 className="mt-5 text-3xl font-semibold tracking-tight">{plan.price}</h2>
            <p className={`mt-4 min-h-14 text-sm leading-relaxed ${plan.featured ? 'text-fog' : 'text-pewter'}`}>{plan.detail}</p>
            <ul className="mt-8 space-y-4">
              {plan.features.map((feature) => <li key={feature} className={`flex gap-3 text-sm ${plan.featured ? 'text-fog' : 'text-charcoal'}`}><Check className="h-4 w-4 shrink-0 text-ember-orange" />{feature}</li>)}
            </ul>
            <div className="mt-auto pt-10">
              {plan.name === 'Explorer' && !user ? <GoogleSignInButton className="w-full" /> : <Link to={user ? '/app' : '/docs'} className={`inline-flex w-full justify-center rounded-full px-5 py-2.5 text-sm font-semibold transition ${plan.featured ? 'bg-pure-white text-ink-black hover:bg-fog' : 'bg-ink-black text-pure-white hover:bg-charcoal'}`}>{user ? 'Open workspace' : 'Read the docs'}</Link>}
            </div>
          </article>
        ))}
      </div>
    </main>
  );
};

export default PricingPage;
