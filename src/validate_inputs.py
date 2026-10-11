
import csv
import json
from pathlib import Path


# Project root directory
PROJECT_ROOT = Path(__file__).resolve().parent.parent

CONFIG_PATH = PROJECT_ROOT / "config" / "pipeline_config_full.json"

EXPECTED_COLUMNS = {
    "device_info": [
        "device_identifier",
        "device_serial",
        "img_serial_number",
        "dtr_name",
        "latitude",
        "longitude",
        "meter_type",
        "commissioned_on",
    ],
    "hes_blockload": [
        "device_serial",
        "data_timestamp",
        "import_wh",
        "voltage_v",
        "current_a",
    ],
    "mdms_daily_load": [
        "device_identifier",
        "load_date",
        "total_import_kwh",
        "is_estimated",
    ],
    "meter_events": [
        "device_identifier",
        "event_code",
        "event_timestamp_ist",
        "created_at_utc",
    ],
    "billing_profile": [
        "device_identifier",
        "billing_month",
        "opening_kwh",
        "closing_kwh",
        "mdm_connection_status",
        "bill_status",
    ],
}


def load_config():
    """Load pipeline settings from JSON."""
    if not CONFIG_PATH.is_file():
        raise FileNotFoundError(
            f"Configuration file not found: {CONFIG_PATH}"
        )

    with CONFIG_PATH.open("r", encoding="utf-8-sig") as file:
        config = json.load(file)

    required_keys = [
        "dataset_mode",
        "input_dir",
        "output_dir",
        "checkpoint_dir",
        "window_start",
        "window_end_exclusive",
        "interval_minutes",
        "chunk_size",
        "dtr_loss_threshold_percent",
    ]

    missing_keys = [
        key for key in required_keys if key not in config
    ]

    if missing_keys:
        raise ValueError(
            f"Missing configuration keys: {missing_keys}"
        )

    return config


def validate_inputs(config):
    """Check that all required CSV files and headers are present."""
    data_dir = PROJECT_ROOT / config["input_dir"]
    errors = []
    row_counts = {}

    for table_name, expected_columns in EXPECTED_COLUMNS.items():
        csv_path = data_dir / f"{table_name}.csv"

        if not csv_path.is_file():
            errors.append(f"Missing file: {csv_path}")
            continue

        with csv_path.open(
            "r", encoding="utf-8-sig", newline=""
        ) as file:
            reader = csv.reader(file)
            actual_columns = next(reader, None)

            if actual_columns != expected_columns:
                errors.append(
                    f"Header mismatch in {csv_path.name}\n"
                    f"Expected: {expected_columns}\n"
                    f"Actual:   {actual_columns}"
                )
                continue

            row_counts[table_name] = sum(1 for _ in reader)

    if errors:
        raise ValueError(
            "Input validation failed:\n- " + "\n- ".join(errors)
        )

    return row_counts


def main():
    config = load_config()

    print("Configuration loaded successfully.")
    print(f"Dataset mode: {config['dataset_mode']}")
    print(f"Input directory: {config['input_dir']}")

    row_counts = validate_inputs(config)

    print("\nCSV validation successful!")
    print("-" * 45)

    for table_name, count in row_counts.items():
        print(f"{table_name:20} {count:>10,} rows")

    print("-" * 45)
    print(f"Total rows: {sum(row_counts.values()):,}")


if __name__ == "__main__":
    main()
