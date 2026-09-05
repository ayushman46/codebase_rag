import { Check } from 'lucide-react';
import { Link } from 'react-router-dom';
import GoogleSignInButton from '../components/GoogleSignInButton';
import RazorpayCheckoutButton from '../components/RazorpayCheckoutButton';
import useStore from '../store/useStore';

const plans = [
  {
    name: 'Explorer',
    availability: 'Available now',
    price: 'Free',
    detail: 'Everything you need to evaluate a repository and learn the workflow.',
    features: ['Google account workspace', 'Public repository ingestion', 'Grounded answers with citations', 'Up to 200 MB of total indexed repositories'],
  },
  {
    name: 'Team',
    availability: 'Available now',
    price: '₹300 / month',
    detail: 'More room for multiple repositories and a higher cumulative indexing limit for your workspace.',
    features: ['Everything in Explorer', 'Up to 800 MB across your workspace', 'Higher indexing capacity', 'Priority support'],
  },
];

const PricingPage = () => {
  const { user } = useStore();
  return (
    <main className="content-shell page-section">
      <div className="mx-auto max-w-2xl text-center">
        <span className="text-caption font-semibold uppercase tracking-widest text-ember-orange">Pricing</span>
        <h1 className="heading-lg page-title mt-5 text-ink-black">Choose the right place to start.</h1>
        <p className="mt-5 text-lg leading-relaxed text-pewter">Begin with a private workspace today, then expand your indexed source capacity when your projects grow.</p>
      </div>
      <div className="mx-auto mt-12 grid max-w-5xl gap-5 md:mt-16 md:grid-cols-2 md:gap-6">
        {plans.map((plan) => (
          <article key={plan.name} className="flex min-h-full flex-col rounded-3xl border border-sand bg-pure-white p-7 sm:p-9">
            <div className="flex items-start justify-between gap-4">
              <h2 className="text-3xl font-semibold tracking-tight text-ink-black">{plan.name}</h2>
              <p className="pt-1 text-caption font-semibold uppercase tracking-widest text-ember-orange">{plan.availability}</p>
            </div>
            <p className="mt-8 text-4xl font-semibold tracking-tight text-ink-black sm:text-5xl">{plan.price}</p>
            <p className="mt-4 max-w-sm text-base leading-relaxed text-pewter">{plan.detail}</p>
            <div className="mt-9">
              {plan.name === 'Explorer' && !user ? (
                <GoogleSignInButton className="w-full justify-center" />
              ) : plan.name === 'Team' ? (
                <RazorpayCheckoutButton />
              ) : (
                <Link to="/app" className="inline-flex w-full justify-center rounded-full bg-ink-black px-5 py-3 text-sm font-semibold text-pure-white transition hover:bg-charcoal">
                  Open workspace
                </Link>
              )}
            </div>
            <div className="mt-10 border-t border-sand pt-7">
              <h3 className="text-sm font-semibold text-ink-black">What’s included</h3>
              <ul className="mt-5 space-y-4">
                {plan.features.map((feature) => <li key={feature} className="flex gap-3 text-sm leading-relaxed text-charcoal">{feature}</li>)}
              </ul>
            </div>
          </article>
        ))}
      </div>
    </main>
  );
};

export default PricingPage;
