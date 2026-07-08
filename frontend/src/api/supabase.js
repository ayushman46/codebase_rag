import { createClient } from '@supabase/supabase-js';

const supabaseUrl = import.meta.env.VITE_SUPABASE_URL || '';
const supabaseAnonKey = import.meta.env.VITE_SUPABASE_ANON_KEY || '';

// Validate URL structure to prevent Supabase SDK from crashing on startup
const isValidUrl = (url) => {
  try {
    new URL(url);
    return true;
  } catch (e) {
    return false;
  }
};

// Defensive fallback client in case .env keys are not yet configured
export const supabase = (supabaseUrl && supabaseAnonKey && isValidUrl(supabaseUrl))
  ? createClient(supabaseUrl, supabaseAnonKey)
  : {
      auth: {
        getSession: async () => ({ data: { session: null } }),
        onAuthStateChange: () => ({ data: { subscription: { unsubscribe: () => {} } } }),
        signInWithOAuth: async () => { 
          alert("Please configure VITE_SUPABASE_URL and VITE_SUPABASE_ANON_KEY inside your .env file to enable authentication."); 
          return { error: null }; 
        },
        signOut: async () => ({ error: null })
      }
    };
