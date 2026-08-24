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
      <div className="mx-auto mt-12 grid max-w-5xl border-t border-sand md:mt-16 md:grid-cols-2 md:divide-x md:divide-sand">
        {plans.map((plan) => (
          <article key={plan.name} className="flex flex-col border-b border-sand py-10 first:md:pr-10 last:md:pl-10 md:border-b-0 md:py-12">
            <p className="text-sm font-semibold text-ember-orange">{plan.name}</p>
            <h2 className="mt-4 text-4xl font-semibold tracking-tight text-ink-black">{plan.price}</h2>
            <p className="mt-4 max-w-sm text-sm leading-relaxed text-pewter">{plan.detail}</p>
            <ul className="mt-8 space-y-4 border-t border-sand pt-7">
              {plan.features.map((feature) => <li key={feature} className="flex gap-3 text-sm text-charcoal"><Check className="h-4 w-4 shrink-0 text-ember-orange" />{feature}</li>)}
            </ul>
            <div className="mt-10">
              {plan.name === 'Explorer' && !user ? <GoogleSignInButton className="w-full sm:w-auto" /> : <Link to={user ? '/app' : '/docs'} className="inline-flex w-full justify-center rounded-full bg-ink-black px-5 py-2.5 text-sm font-semibold text-pure-white transition hover:bg-charcoal sm:w-auto">{user ? 'Open workspace' : 'Read the docs'}</Link>}
            </div>
          </article>
        ))}
      </div>
    </main>
  );
};

export default PricingPage;
