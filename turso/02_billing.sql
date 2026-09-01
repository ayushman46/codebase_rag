-- Additive billing/quota migration for existing Codebase Intel Turso databases.
-- Run after turso/00_init.sql and turso/01_trust_features.sql.

PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS account_entitlements (
  user_id TEXT PRIMARY KEY,
  plan TEXT NOT NULL DEFAULT 'explorer' CHECK (plan IN ('explorer', 'team')),
  quota_bytes INTEGER NOT NULL DEFAULT 500000000 CHECK (quota_bytes > 0),
  status TEXT NOT NULL DEFAULT 'active' CHECK (status IN ('active', 'past_due', 'cancelled')),
  razorpay_order_id TEXT,
  razorpay_payment_id TEXT,
  updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS billing_orders (
  id TEXT PRIMARY KEY,
  user_id TEXT NOT NULL,
  plan TEXT NOT NULL CHECK (plan = 'team'),
  razorpay_order_id TEXT NOT NULL UNIQUE,
  amount INTEGER NOT NULL CHECK (amount >= 100),
  currency TEXT NOT NULL DEFAULT 'INR',
  status TEXT NOT NULL DEFAULT 'created' CHECK (status IN ('created', 'paid', 'failed')),
  razorpay_payment_id TEXT UNIQUE,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS billing_orders_user_status ON billing_orders(user_id, status, created_at);
