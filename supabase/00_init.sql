-- Supabase is used only for authentication in this version of Codebase Intelligence.
-- No application tables, RLS policies, pgvector extension, or RPC functions are required here.
--
-- Configure Google OAuth in Supabase Authentication instead. Application data
-- lives in Turso; run turso/00_init.sql there before starting the backend.

SELECT 'Supabase Auth configured separately; Turso owns application data.' AS migration_note;
