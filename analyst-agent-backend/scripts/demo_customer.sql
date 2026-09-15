-- Seeds the local `demo` database: the development and integration-test fixture standing in
-- for a customer's own Postgres. Run as the postgres superuser:
--   & "D:\postgres\bin\psql.exe" -U postgres -d demo -f scripts\demo_customer.sql
-- Idempotent: safe to re-run.

DROP TABLE IF EXISTS gps_pings;
DROP TABLE IF EXISTS trips;
DROP TABLE IF EXISTS readings;
DROP TABLE IF EXISTS telemetry;
DROP TABLE IF EXISTS batteries;
DROP TABLE IF EXISTS dealers;
-- Not created here, but it was in the database and survived every reseed, so it turned up in
-- the tool description on every run. The script defines the fixture; it has to own removal too.
DROP TABLE IF EXISTS data;

CREATE TABLE dealers (
    id         SERIAL PRIMARY KEY,
    name       TEXT NOT NULL,
    city       TEXT NOT NULL,
    created_at DATE NOT NULL
);

CREATE TABLE batteries (
    id           SERIAL PRIMARY KEY,
    dealer_id    INT REFERENCES dealers (id),
    imei         TEXT UNIQUE NOT NULL,
    chemistry    TEXT NOT NULL,
    capacity_kwh NUMERIC(5, 2) NOT NULL,
    sold_on      DATE NOT NULL,
    price_inr    NUMERIC(12, 2) NOT NULL
);

CREATE TABLE telemetry (
    id         BIGSERIAL PRIMARY KEY,
    battery_id INT REFERENCES batteries (id),
    ts         TIMESTAMPTZ NOT NULL,
    soc        NUMERIC(5, 2),
    voltage    NUMERIC(6, 2),
    temp_c     NUMERIC(5, 2)
);

INSERT INTO dealers (name, city, created_at) VALUES
    ('Sharma Motors', 'Gurugram', '2026-01-10'),
    ('Roy Auto',      'Howrah',   '2026-02-14'),
    ('Patil EV',      'Nashik',   '2026-03-02');

INSERT INTO batteries (dealer_id, imei, chemistry, capacity_kwh, sold_on, price_inr) VALUES
    (1, '860000000000001', 'LFP',  7.2, '2026-07-05', 48500),
    (1, '860000000000002', 'LFP',  7.2, '2026-08-12', 48500),
    (2, '860000000000003', 'LFP', 10.0, '2026-08-20', 61000),
    (3, '860000000000004', 'LFP',  7.2, '2026-08-28', 47800),
    (3, '860000000000005', 'LFP', 10.0, '2026-09-01', 60500);

-- A range-partitioned table, mirroring the real IoT schema where `telemetry_gps`, `trips`
-- and `alerts` are partitioned weekly. The agent must be shown the parent and never the
-- children, so the fixture has to contain both.
CREATE TABLE readings (
    id         BIGSERIAL,
    battery_id INT NOT NULL,
    ts         TIMESTAMPTZ NOT NULL,
    soc        NUMERIC(5, 2)
) PARTITION BY RANGE (ts);

CREATE TABLE readings_p20260901 PARTITION OF readings
    FOR VALUES FROM ('2026-09-01') TO ('2026-09-08');
CREATE TABLE readings_p20260908 PARTITION OF readings
    FOR VALUES FROM ('2026-09-08') TO ('2026-09-15');

INSERT INTO readings (battery_id, ts, soc) VALUES
    (1, '2026-09-02 10:00+00', 55.0),
    (2, '2026-09-03 11:00+00', 61.5),
    (3, '2026-09-09 12:00+00', 48.25);

-- 48 hourly readings per battery: 5 x 48 = 240 rows.
INSERT INTO telemetry (battery_id, ts, soc, voltage, temp_c)
SELECT b.id,
       now() - (g || ' hours')::interval,
       20 + random() * 80,
       48 + random() * 6,
       25 + random() * 15
  FROM batteries b, generate_series(1, 48) g;

-- The two shapes the agent has to tell apart on the real IoT database, where 7 of 15 tables
-- hold nothing and the telemetry pipeline stopped in early July. Without them a missing-data
-- eval against this fixture would pass or fail for reasons unrelated to what it is testing.

-- Never populated, like `trips` and `telemetry_fuel` upstream.
CREATE TABLE trips (
    id         BIGSERIAL PRIMARY KEY,
    battery_id INT REFERENCES batteries (id),
    started_at TIMESTAMPTZ NOT NULL,
    ended_at   TIMESTAMPTZ,
    distance_km NUMERIC(8, 2)
);

-- Stopped feeding in early July, with a partition already created ahead of the data. That
-- empty partition is the point: reading the newest bound rather than the newest bound that
-- holds rows would advertise coverage to 07-13 for a table that ends on 07-02.
CREATE TABLE gps_pings (
    id         BIGSERIAL,
    battery_id INT NOT NULL,
    ts         TIMESTAMPTZ NOT NULL,
    lat        NUMERIC(9, 6),
    lon        NUMERIC(9, 6)
) PARTITION BY RANGE (ts);

CREATE TABLE gps_pings_p20260622 PARTITION OF gps_pings
    FOR VALUES FROM ('2026-06-22 00:00:00+00') TO ('2026-06-29 00:00:00+00');
CREATE TABLE gps_pings_p20260629 PARTITION OF gps_pings
    FOR VALUES FROM ('2026-06-29 00:00:00+00') TO ('2026-07-06 00:00:00+00');
CREATE TABLE gps_pings_p20260706 PARTITION OF gps_pings
    FOR VALUES FROM ('2026-07-06 00:00:00+00') TO ('2026-07-13 00:00:00+00');

INSERT INTO gps_pings (battery_id, ts, lat, lon) VALUES
    (1, '2026-06-23 08:00+00', 28.459497, 77.026638),
    (2, '2026-06-27 14:30+00', 22.589800, 88.310600),
    (3, '2026-07-01 09:15+00', 19.997500, 73.789800),
    (4, '2026-07-02 17:45+00', 28.459497, 77.026638);

-- Without this every table reports as never analysed, so the row buckets in the tool
-- description would flip from "nonempty" to "few" the moment autovacuum caught up, and the
-- eval cassettes fingerprint that description.
ANALYZE;

DO $$
BEGIN
    IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname = 'analyst_ro') THEN
        CREATE ROLE analyst_ro LOGIN PASSWORD 'ro';
    END IF;
END
$$;

GRANT CONNECT ON DATABASE demo TO analyst_ro;
GRANT USAGE ON SCHEMA public TO analyst_ro;
GRANT SELECT ON ALL TABLES IN SCHEMA public TO analyst_ro;
ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT SELECT ON TABLES TO analyst_ro;
ALTER ROLE analyst_ro SET statement_timeout = '8s';
ALTER ROLE analyst_ro SET default_transaction_read_only = on;
