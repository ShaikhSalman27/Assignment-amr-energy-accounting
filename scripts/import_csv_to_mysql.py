
import csv
import getpass
from pathlib import Path

import mysql.connector

ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = ROOT / "data_full"
BATCH_SIZE = 5000

TABLES = {
    "device_info": [
        "device_identifier", "device_serial", "img_serial_number",
        "dtr_name", "latitude", "longitude", "meter_type",
        "commissioned_on"
    ],
    "hes_blockload": [
        "device_serial", "data_timestamp", "import_wh",
        "voltage_v", "current_a"
    ],
    "mdms_daily_load": [
        "device_identifier", "load_date", "total_import_kwh",
        "is_estimated"
    ],
    "meter_events": [
        "device_identifier", "event_code", "event_timestamp_ist",
        "created_at_utc"
    ],
    "billing_profile": [
        "device_identifier", "billing_month", "opening_kwh",
        "closing_kwh", "mdm_connection_status", "bill_status"
    ],
}


def main():
    username = "root"
    password = getpass.getpass("MySQL password: ")

    connection = mysql.connector.connect(
        host="localhost",
        port=3306,
        user=username,
        password=password,
        database="amr_assignment_full",
    )

    try:
        connection.start_transaction()
        cursor = connection.cursor()

        # Validate all files before changing database contents.
        for table, columns in TABLES.items():
            path = DATA_DIR / f"{table}.csv"

            if not path.is_file():
                raise FileNotFoundError(f"CSV not found: {path}")

            with path.open("r", encoding="utf-8-sig", newline="") as f:
                reader = csv.reader(f)
                header = next(reader, None)

            if header != columns:
                raise ValueError(
                    f"Unexpected header in {path.name}: {header}"
                )

        # Replace existing data on a successful rerun.
        for table in TABLES:
            cursor.execute(f"DELETE FROM `{table}`")

        for table, columns in TABLES.items():
            path = DATA_DIR / f"{table}.csv"
            column_sql = ", ".join(f"`{c}`" for c in columns)
            placeholders = ", ".join(["%s"] * len(columns))
            query = (
                f"INSERT INTO `{table}` ({column_sql}) "
                f"VALUES ({placeholders})"
            )

            total = 0
            batch = []

            with path.open("r", encoding="utf-8-sig", newline="") as f:
                reader = csv.DictReader(f)

                for row in reader:
                    values = [row[c] or None for c in columns]

                    if table == "mdms_daily_load":
                        idx = columns.index("is_estimated")
                        value = (values[idx] or "").lower()

                        if value not in ("true", "false", "1", "0"):
                            raise ValueError(
                                f"Invalid is_estimated: {value!r}"
                            )

                        values[idx] = value in ("true", "1")

                    batch.append(tuple(values))

                    if len(batch) >= BATCH_SIZE:
                        cursor.executemany(query, batch)
                        total += len(batch)
                        batch.clear()

                if batch:
                    cursor.executemany(query, batch)
                    total += len(batch)

            print(f"{table}: {total:,} rows loaded")

        connection.commit()
        print("Import completed successfully.")

    except Exception:
        connection.rollback()
        raise

    finally:
        connection.close()


if __name__ == "__main__":
    main()
