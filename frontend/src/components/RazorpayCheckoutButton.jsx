import { Check, Loader2, LockKeyhole, Send, X } from 'lucide-react';
import { useEffect, useRef, useState } from 'react';
import { createTeamOrder, verifyTeamPayment } from '../api/client';
import useStore from '../store/useStore';

let razorpayScriptPromise;
const PENDING_CHECKOUT_KEY = 'codebase-intel.pending-team-checkout';

const loadRazorpayScript = () => {
  if (typeof window === 'undefined') return Promise.reject(new Error('Checkout is only available in a browser.'));
  if (window.Razorpay) return Promise.resolve();
  if (razorpayScriptPromise) return razorpayScriptPromise;

  razorpayScriptPromise = new Promise((resolve, reject) => {
    const script = document.createElement('script');
    script.src = 'https://checkout.razorpay.com/v1/checkout.js';
    script.async = true;
    script.onload = () => (window.Razorpay ? resolve() : reject(new Error('Razorpay checkout could not be loaded.')));
    script.onerror = () => reject(new Error('Razorpay checkout could not be loaded. Check your connection and try again.'));
    document.body.appendChild(script);
  }).catch((error) => {
    razorpayScriptPromise = undefined;
    throw error;
  });

  return razorpayScriptPromise;
};

const providerError = (error) => {
  const detail = error?.response?.data?.detail;
  return typeof detail === 'string' && detail.trim()
    ? detail
    : error?.message || 'Team checkout could not be completed. Please try again.';
};

const RazorpayCheckoutButton = ({ className = '', onSuccess }) => {
  const { user, signInWithGoogle, isSigningIn } = useStore();
  const [state, setState] = useState('idle');
  const [message, setMessage] = useState('');
  const mountedRef = useRef(true);
  const busyRef = useRef(false);

  useEffect(() => () => {
    mountedRef.current = false;
  }, []);

  const update = (nextState, nextMessage = '') => {
    if (mountedRef.current) {
      setState(nextState);
      setMessage(nextMessage);
    }
  };

  const handleCheckout = async () => {
    if (busyRef.current) return;
    if (!user) {
      // Keep the user's one-click intent across the OAuth redirect. Once the
      // session is restored, the effect below resumes checkout automatically.
      try {
        window.sessionStorage.setItem(PENDING_CHECKOUT_KEY, '1');
      } catch {
        // Storage can be disabled in privacy-restricted browsers; the user can
        // still return and click the button again after signing in.
      }
      const signInStarted = await signInWithGoogle();
      if (signInStarted === false) {
        try {
          window.sessionStorage.removeItem(PENDING_CHECKOUT_KEY);
        } catch {
          // Ignore storage failures; the visible error remains actionable.
        }
        update('error', 'Google sign-in could not be started. Check your authentication settings and try again.');
      }
      return;
    }

    busyRef.current = true;
    update('loading');
    try {
      const { data: order } = await createTeamOrder();
      // Prefer the server-provided public key. This prevents a stale/missing
      // Vite build variable from making an otherwise configured checkout look
      // inert. The key is intentionally public; the secret never leaves the
      // backend.
      const publicKey = String(order?.key_id || import.meta.env.VITE_RAZORPAY_KEY_ID || '').trim();
      if (!publicKey) {
        throw new Error('Team checkout is not configured for this environment.');
      }
      if (!order?.order_id || Number(order.amount) < 100 || order.currency !== 'INR') {
        throw new Error('The checkout order returned by the server is invalid.');
      }
      await loadRazorpayScript();

      const checkout = new window.Razorpay({
        key: publicKey,
        amount: order.amount,
        currency: order.currency,
        name: 'Codebase Intel',
        description: 'Codebase Intel Team plan',
        order_id: order.order_id,
        prefill: {
          name: user.user_metadata?.full_name || '',
          email: user.email || '',
        },
        theme: { color: '#ff9b88' },
        handler: async (response) => {
          update('verifying', 'Confirming your payment…');
          try {
            await verifyTeamPayment({
              razorpay_payment_id: response.razorpay_payment_id,
              razorpay_order_id: response.razorpay_order_id,
              razorpay_signature: response.razorpay_signature,
            });
            busyRef.current = false;
            update('success', 'Team plan is active for your workspace.');
            await onSuccess?.();
          } catch (error) {
            busyRef.current = false;
            update('error', providerError(error));
          }
        },
        modal: {
          ondismiss: () => {
            busyRef.current = false;
            update('cancelled', 'Checkout cancelled. No payment was recorded.');
          },
        },
      });

      checkout.on('payment.failed', (response) => {
        const description = response?.error?.description;
        // Keep the trigger locked while Razorpay's modal is still open. The
        // user can retry inside the modal; ondismiss releases the guard.
        update('open', description ? `Payment failed: ${description}` : 'Payment failed. No payment was recorded.');
      });
      checkout.open();
      update('open');
    } catch (error) {
      busyRef.current = false;
      update('error', providerError(error));
    }
  };

  useEffect(() => {
    if (!user || busyRef.current) return;
    let pending = false;
    try {
      pending = window.sessionStorage.getItem(PENDING_CHECKOUT_KEY) === '1';
      if (pending) window.sessionStorage.removeItem(PENDING_CHECKOUT_KEY);
    } catch {
      pending = false;
    }
    if (pending) void handleCheckout();
  }, [user]);

  const disabled = isSigningIn || ['loading', 'verifying', 'success', 'open'].includes(state);
  const label = state === 'loading'
    ? 'Preparing checkout…'
    : state === 'verifying'
      ? 'Confirming payment…'
      : state === 'success'
        ? 'Team plan active'
        : user
          ? 'Choose Team · ₹300/month'
          : 'Sign in to choose Team';

  return (
    <div>
      <button
        type="button"
        onClick={handleCheckout}
        disabled={disabled}
        aria-busy={['loading', 'verifying'].includes(state)}
        data-testid="choose-team-button"
        className={`inline-flex min-h-12 w-full items-center justify-center gap-2 rounded-full bg-ink-black px-5 py-3 text-sm font-semibold text-pure-white transition hover:bg-charcoal disabled:cursor-not-allowed disabled:opacity-60 ${className}`}
      >
        {state === 'success' ? <Check className="h-4 w-4" aria-hidden="true" /> : state === 'cancelled' ? <X className="h-4 w-4" aria-hidden="true" /> : state === 'loading' || state === 'verifying' ? <Loader2 className="h-4 w-4 animate-spin" aria-hidden="true" /> : <Send className="h-4 w-4" aria-hidden="true" />}
        {label}
      </button>
      <p className="mt-3 flex items-center justify-center gap-1.5 text-xs text-warm-gray"><LockKeyhole className="h-3.5 w-3.5" aria-hidden="true" />Secure payment through Razorpay</p>
      {message && <p className={`mt-3 text-center text-sm leading-relaxed ${state === 'error' ? 'text-red-700' : state === 'success' ? 'text-emerald-700' : 'text-pewter'}`} role={state === 'error' ? 'alert' : 'status'}>{message}</p>}
    </div>
  );
};

export default RazorpayCheckoutButton;
