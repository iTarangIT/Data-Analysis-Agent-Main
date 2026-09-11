-- One-time local setup: the App DB and the Checkpoint DB.
-- Runs in psql or in the pgAdmin Query Tool. Connect to the `postgres` database as a superuser.
--   & "D:\postgres\bin\psql.exe" -U postgres -f scripts\bootstrap_local_db.sql
-- The demo customer database is seeded separately by scripts/demo_customer.sql.

-- Roles first. This block is idempotent.
DO $$
BEGIN
    IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname = 'app') THEN
        CREATE ROLE app LOGIN PASSWORD 'app';
    END IF;
    IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname = 'ckpt') THEN
        CREATE ROLE ckpt LOGIN PASSWORD 'ckpt';
    END IF;
    IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname = 'demo') THEN
        CREATE ROLE demo LOGIN PASSWORD 'demo';
    END IF;
END
$$;

-- CREATE DATABASE has no IF NOT EXISTS and cannot run inside a transaction, so these three
-- are plain statements and each must be sent to the server ON ITS OWN.
--
-- In pgAdmin: select one line and press F5, three times. Running them together gives
--   ERROR: CREATE DATABASE cannot run inside a transaction block   (SQLSTATE 25001)
-- because a multi-statement send is an implicit transaction. Auto-commit does not change this.
-- psql -f handles them correctly without any of this.
--
-- If a database already exists you get
--   ERROR: database "analyst" already exists
-- which is safe to ignore.
CREATE DATABASE analyst OWNER app;
CREATE DATABASE checkpoints OWNER ckpt;
CREATE DATABASE demo OWNER demo;
