-- Load the generated CSVs into PostgreSQL.
--   createdb amr_assignment
--   psql amr_assignment -v data_dir=/abs/path/to/data -f schema.sql
-- No indexes are created on purpose. Adding the right ones is part of the task.

DROP TABLE IF EXISTS hes_blockload, mdms_daily_load, meter_events, billing_profile, device_info;

CREATE TABLE device_info (
    device_identifier   text,
    device_serial       text,
    img_serial_number   text,
    dtr_name            text,
    latitude            double precision,
    longitude           double precision,
    meter_type          text,
    commissioned_on     date
);

-- data_timestamp is LITERAL IST stored as a naive timestamp (no tz).
CREATE TABLE hes_blockload (
    device_serial   text,
    data_timestamp  timestamp,
    import_wh       double precision,
    voltage_v       double precision,
    current_a       double precision
);

CREATE TABLE mdms_daily_load (
    device_identifier text,
    load_date         date,
    total_import_kwh  double precision,
    is_estimated      boolean
);

-- event_timestamp_ist is literal IST; created_at_utc is UTC. They are not the same clock.
CREATE TABLE meter_events (
    device_identifier   text,
    event_code          int,
    event_timestamp_ist timestamp,
    created_at_utc      timestamp
);

CREATE TABLE billing_profile (
    device_identifier     text,
    billing_month         text,
    opening_kwh           double precision,
    closing_kwh           double precision,
    mdm_connection_status text,
    bill_status           text
);

\copy device_info      FROM :'data_dir'/device_info.csv      CSV HEADER
\copy hes_blockload    FROM :'data_dir'/hes_blockload.csv    CSV HEADER
\copy mdms_daily_load  FROM :'data_dir'/mdms_daily_load.csv  CSV HEADER
\copy meter_events     FROM :'data_dir'/meter_events.csv     CSV HEADER
\copy billing_profile  FROM :'data_dir'/billing_profile.csv  CSV HEADER

ANALYZE;
