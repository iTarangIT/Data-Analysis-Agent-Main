-- Run as a superuser ON THE CUSTOMER DATABASE, once per customer source.
-- Works in psql and in the pgAdmin Query Tool.
--
-- This is the first of the three layers that keep customer data read-only. The other two are
-- the connector's connect_args and the SQL guard. All three must hold independently.
--
-- BEFORE RUNNING, replace both placeholders below:
--   CHANGE_ME_PASSWORD  a new password for the analyst_ro login
--   CHANGE_ME_DATABASE  the database you are connected to, e.g. itarang

DO $$
BEGIN
    IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname = 'analyst_ro') THEN
        CREATE ROLE analyst_ro LOGIN PASSWORD 'CHANGE_ME_PASSWORD';
    ELSE
        ALTER ROLE analyst_ro LOGIN PASSWORD 'CHANGE_ME_PASSWORD';
    END IF;
END
$$;

GRANT CONNECT ON DATABASE "CHANGE_ME_DATABASE" TO analyst_ro;
GRANT USAGE ON SCHEMA public TO analyst_ro;
GRANT SELECT ON ALL TABLES IN SCHEMA public TO analyst_ro;
ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT SELECT ON TABLES TO analyst_ro;

-- Belt and braces: even a query that slips past the guard cannot write or run long.
ALTER ROLE analyst_ro SET statement_timeout = '8s';
ALTER ROLE analyst_ro SET default_transaction_read_only = on;

-- Verify as analyst_ro straight afterwards. This DELETE must fail with
--   ERROR: cannot execute DELETE in a read-only transaction
-- If it succeeds, stop: the role is misconfigured.
