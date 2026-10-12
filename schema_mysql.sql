
USE amr_assignment_full;

CREATE TABLE IF NOT EXISTS device_info (
    device_identifier VARCHAR(100),
    device_serial VARCHAR(50),
    img_serial_number VARCHAR(100),
    dtr_name VARCHAR(150),
    latitude DOUBLE,
    longitude DOUBLE,
    meter_type VARCHAR(30),
    commissioned_on DATE
);

CREATE TABLE IF NOT EXISTS hes_blockload (
    device_serial VARCHAR(50),
    data_timestamp DATETIME,
    import_wh DOUBLE,
    voltage_v DOUBLE,
    current_a DOUBLE
);

CREATE TABLE IF NOT EXISTS mdms_daily_load (
    device_identifier VARCHAR(100),
    load_date DATE,
    total_import_kwh DOUBLE,
    is_estimated BOOLEAN
);

CREATE TABLE IF NOT EXISTS meter_events (
    device_identifier VARCHAR(100),
    event_code INT,
    event_timestamp_ist DATETIME,
    created_at_utc DATETIME
);

CREATE TABLE IF NOT EXISTS billing_profile (
    device_identifier VARCHAR(100),
    billing_month VARCHAR(7),
    opening_kwh DOUBLE,
    closing_kwh DOUBLE,
    mdm_connection_status VARCHAR(50),
    bill_status VARCHAR(50)
);

