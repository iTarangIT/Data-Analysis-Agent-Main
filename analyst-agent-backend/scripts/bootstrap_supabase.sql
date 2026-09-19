-- One-time Supabase setup: the App DB and the Checkpoint DB as two schemas of the project's
-- `postgres` database. Run in the dashboard's SQL editor, which connects as `postgres`.
-- The local equivalent is scripts/bootstrap_local_db.sql; the demo customer database is not
-- here, because it is a customer's and never lives beside ours.
--
-- Schemas rather than databases: the dashboard, backups and the pooler all work on `postgres`.
-- Each schema has its own login role that owns it and finds it through its search_path, so
-- Alembic, SQLAlchemy and LangGraph need no schema-qualified names. Neither schema is in the
-- Data API's exposed list, and anon/authenticated are granted nothing on either, so nothing here
-- is reachable with the project's publishable key.

DO $$
BEGIN
    IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname = 'analyst_app') THEN
        CREATE ROLE analyst_app LOGIN;
    END IF;
    IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname = 'analyst_ckpt') THEN
        CREATE ROLE analyst_ckpt LOGIN;
    END IF;
END
$$;

-- Lets the table editor, which connects as postgres, read both schemas; and is what lets
-- postgres create a schema owned by another role.
GRANT analyst_app TO postgres;
GRANT analyst_ckpt TO postgres;

CREATE SCHEMA IF NOT EXISTS analyst AUTHORIZATION analyst_app;
CREATE SCHEMA IF NOT EXISTS checkpoints AUTHORIZATION analyst_ckpt;

ALTER ROLE analyst_app SET search_path = analyst;
ALTER ROLE analyst_ckpt SET search_path = checkpoints;

-- Passwords are set separately so they never land in the migration history. Either type a
-- plaintext one here, or send a SCRAM-SHA-256 verifier computed on your own machine so the
-- plaintext never leaves it:
--   ALTER ROLE analyst_app  PASSWORD '...';
--   ALTER ROLE analyst_ckpt PASSWORD '...';
--
-- Then connect through the session pooler, which is IPv4 (the direct db.<ref>.supabase.co host
-- is IPv6 only). The user is `<role>.<project-ref>`:
--   APP_DB_URL=postgresql+psycopg://analyst_app.<ref>:<pw>@aws-0-<region>.pooler.supabase.com:5432/postgres?sslmode=require
--   CHECKPOINT_DB_URL=postgresql://analyst_ckpt.<ref>:<pw>@aws-0-<region>.pooler.supabase.com:5432/postgres?sslmode=require
-- Session mode (5432), not transaction mode (6543): psycopg prepares statements, and the store's
-- setup issues CREATE INDEX CONCURRENTLY.
--
-- Last, create the tables, from analyst-agent-backend with that .env in place:
--   python -m alembic upgrade head
-- and the checkpointer's four tables, which nothing in the app creates, in a `python` prompt:
--   from langgraph.checkpoint.postgres import PostgresSaver
--   from app.config import get_settings
--   with PostgresSaver.from_conn_string(str(get_settings().checkpoint_db_url)) as saver:
--       saver.setup()
-- The API creates the memory store's tables itself at boot (`setup_store`).
