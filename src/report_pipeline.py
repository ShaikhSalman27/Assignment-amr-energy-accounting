#!/usr/bin/env python3
"""Generate R1/R2/R3 AMR reports from the imported MySQL dataset.

Run from project root:
    python src/report_pipeline.py

Reads config/pipeline_config_full.json, connects to MySQL, and writes stable CSV
outputs under outputs_full/reports. No source rows are modified.
"""
import csv
import getpass
import json
from collections import defaultdict
from datetime import datetime, timedelta
from pathlib import Path

import mysql.connector

ROOT = Path(__file__).resolve().parent.parent
CONFIG_PATH = ROOT / "config" / "pipeline_config_full.json"
IST_SHIFT = timedelta(minutes=330)
ROLLOVER_MODULUS_WH = 100_000_000.0


def read_config():
    with CONFIG_PATH.open("r", encoding="utf-8-sig") as f:
        cfg = json.load(f)
    required = [
        "input_dir", "output_dir", "checkpoint_dir", "window_start",
        "window_end_exclusive", "interval_minutes",
        "dtr_loss_threshold_percent",
    ]
    missing = [key for key in required if key not in cfg]
    if missing:
        raise ValueError(f"Missing config keys: {missing}")
    return cfg


def parse_dt(value):
    if isinstance(value, datetime):
        return value
    return datetime.strptime(str(value), "%Y-%m-%d %H:%M:%S")


def write_csv(path, fieldnames, rows):
    path.parent.mkdir(parents=True, exist_ok=True)
    # Stable ordering is supplied by callers; fixed newline/encoding makes
    # repeated runs byte-stable on the same Python platform.
    with path.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames, extrasaction="ignore")
        writer.writeheader()
        for row in rows:
            writer.writerow({
                key: ("" if row.get(key) is None else row.get(key))
                for key in fieldnames
            })


def main():
    cfg = read_config()
    start = parse_dt(cfg["window_start"])
    end_exclusive = parse_dt(cfg["window_end_exclusive"])
    interval = int(cfg["interval_minutes"])
    expected = int((end_exclusive - start).total_seconds() // (interval * 60))
    threshold = float(cfg["dtr_loss_threshold_percent"])
    output_dir = ROOT / cfg["output_dir"] / "reports"
    output_dir.mkdir(parents=True, exist_ok=True)

    password = getpass.getpass("MySQL password: ")
    conn = mysql.connector.connect(
        host=cfg.get("mysql_host", "localhost"),
        port=int(cfg.get("mysql_port", 3306)),
        user=cfg.get("mysql_user", "root"),
        password=password,
        database=cfg.get("mysql_database", "amr_assignment_full"),
    )

    exceptions = []
    try:
        cur = conn.cursor(dictionary=True)
        cur.execute("""
            SELECT device_identifier, device_serial, img_serial_number,
                   dtr_name, meter_type, commissioned_on
            FROM device_info
            ORDER BY device_identifier, device_serial, dtr_name
        """)
        master_rows = cur.fetchall()

        # Keep every mapping row; do not silently multiply energy through joins.
        by_identifier = defaultdict(list)
        by_serial = defaultdict(list)
        dtr_master = {}
        for row in master_rows:
            row["device_serial"] = str(row["device_serial"] or "").strip()
            by_identifier[str(row["device_identifier"])].append(row)
            if row["device_serial"]:
                by_serial[row["device_serial"]].append(row)
            if row["meter_type"] == "DT":
                dtr_master[row["dtr_name"]] = row

        cur.execute("""
            SELECT device_identifier, billing_month, opening_kwh, closing_kwh,
                   mdm_connection_status, bill_status
            FROM billing_profile
            WHERE billing_month = '2026-09'
            ORDER BY device_identifier
        """)
        billing = {}
        for row in cur.fetchall():
            billing[str(row["device_identifier"])] = row

        cur.execute("""
            SELECT device_identifier, event_code, event_timestamp_ist,
                   created_at_utc
            FROM meter_events
            WHERE event_code IN (101, 102)
              AND event_timestamp_ist >= %s
              AND event_timestamp_ist < %s
            ORDER BY device_identifier, event_timestamp_ist, event_code
        """, (start, end_exclusive))
        events_by_id = defaultdict(list)
        for row in cur.fetchall():
            key = str(row["device_identifier"])
            events_by_id[key].append(row)

        # A supporting lookup only; HES cumulative registers remain authoritative
        # for R2 because MDMS values can be estimated or inconsistent.
        cur.execute("""
            SELECT device_identifier, load_date, total_import_kwh, is_estimated
            FROM mdms_daily_load
            WHERE load_date >= %s AND load_date < %s
            ORDER BY device_identifier, load_date
        """, (start.date(), end_exclusive.date()))
        daily_by_id = defaultdict(list)
        for row in cur.fetchall():
            daily_by_id[str(row["device_identifier"])].append(row)

        # Stream rows ordered by serial and timestamp so the large HES table
        # does not need to be loaded into Python memory all at once.
        read_summary = {}
        serial_energy = {}
        cur.close()
        stream = conn.cursor(dictionary=True, buffered=False)
        stream.execute("""
            SELECT device_serial, data_timestamp, import_wh, voltage_v, current_a
            FROM hes_blockload
            ORDER BY device_serial, data_timestamp, import_wh
        """)

        current_serial = None
        serial_rows = []
        processed = 0

        def process_serial(serial, rows):
            if not serial:
                return
            # Collapse exact duplicate (timestamp, register) pairs and detect
            # the planted same-register +330-minute timestamp conversion.
            unique = []
            seen_pairs = set()
            seen_register_times = defaultdict(list)
            shifted_rows = []
            duplicate_rows = 0
            outside_rows = []
            for row in rows:
                ts = parse_dt(row["data_timestamp"])
                try:
                    value = float(row["import_wh"])
                except (TypeError, ValueError):
                    exceptions.append({
                        "exception_id": f"INVALID_REGISTER:{serial}:{ts}",
                        "device_serial": serial,
                        "device_identifier": "",
                        "dtr_name": "",
                        "reason": "INVALID_REGISTER_VALUE",
                        "evidence": f"data_timestamp={ts}; import_wh={row['import_wh']!r}",
                        "handling": "Excluded from communication and energy calculations",
                    })
                    continue
                pair = (ts, value)
                if pair in seen_pairs:
                    duplicate_rows += 1
                    continue
                seen_pairs.add(pair)

                is_shifted = any(
                    old_value == value and ts - old_ts == IST_SHIFT
                    for old_ts, old_value in seen_register_times[value]
                )
                seen_register_times[value].append((ts, value))
                if is_shifted:
                    shifted_rows.append((ts, value))
                    exceptions.append({
                        "exception_id": f"SHIFTED_TIMESTAMP:{serial}:{ts}",
                        "device_serial": serial,
                        "device_identifier": "",
                        "dtr_name": "",
                        "reason": "POSSIBLE_IST_UTC_SHIFT_PLUS_330_MIN",
                        "evidence": f"same import_wh={value} appears at a timestamp exactly 330 minutes earlier",
                        "handling": "Excluded as probable shifted duplicate; verify source timestamps",
                    })
                    continue
                if ts < start or ts >= end_exclusive:
                    outside_rows.append((ts, value))
                    exceptions.append({
                        "exception_id": f"OUT_OF_WINDOW:{serial}:{ts}",
                        "device_serial": serial,
                        "device_identifier": "",
                        "dtr_name": "",
                        "reason": "HES_TIMESTAMP_OUTSIDE_REPORTING_WINDOW",
                        "evidence": f"data_timestamp={ts}; reporting_window=[{start}, {end_exclusive})",
                        "handling": "Excluded from R1/R2 reporting window",
                    })
                    continue
                unique.append((ts, value))

            unique.sort()
            slots = set()
            valid_slot_values = {}
            for ts, value in unique:
                # Accept only timestamps aligned to a half-hour slot.
                mins = ts.hour * 60 + ts.minute
                if ts.second != 0 or mins % interval != 0:
                    exceptions.append({
                        "exception_id": f"OFF_GRID_TIMESTAMP:{serial}:{ts}",
                        "device_serial": serial,
                        "device_identifier": "",
                        "dtr_name": "",
                        "reason": "HES_TIMESTAMP_NOT_ON_EXPECTED_INTERVAL",
                        "evidence": f"data_timestamp={ts}",
                        "handling": "Excluded from received-slot count; retained for diagnostics",
                    })
                    continue
                slots.add(ts)
                valid_slot_values[ts] = value

            read_summary[serial] = {
                "slots": slots,
                "first": min(slots) if slots else None,
                "last": max(slots) if slots else None,
                "raw_unique_in_window": len(unique),
                "duplicate_rows": duplicate_rows,
                "shifted_rows": len(shifted_rows),
                "outside_rows": len(outside_rows),
                "register_reset": False,
                "rollover_seen": False,
                "energy_kwh": None,
                "energy_reason": "",
            }

            # Consumption from cumulative registers: deduplicated, chronologically
            # ordered deltas. Positive deltas are accepted; 8-digit rollover is
            # handled explicitly. A reset makes the meter's monthly total unsafe.
            vals = [(ts, valid_slot_values[ts]) for ts in sorted(valid_slot_values)]
            total_wh = 0.0
            reset_found = False
            rollover_found = False
            valid_delta_count = 0
            for (_, previous), (_, current) in zip(vals, vals[1:]):
                delta = current - previous
                if delta < 0:
                    if previous >= 90_000_000 and current < 10_000_000:
                        delta = (ROLLOVER_MODULUS_WH - previous) + current
                        rollover_found = True
                    else:
                        reset_found = True
                        exceptions.append({
                            "exception_id": f"REGISTER_RESET:{serial}",
                            "device_serial": serial,
                            "device_identifier": "",
                            "dtr_name": "",
                            "reason": "CUMULATIVE_REGISTER_RESET_OR_REPLACEMENT",
                            "evidence": f"consecutive register values {previous} -> {current} Wh",
                            "handling": "Monthly energy excluded because reset boundary cannot be reconciled safely",
                        })
                        continue
                total_wh += delta
                valid_delta_count += 1

            summary = read_summary[serial]
            summary["register_reset"] = reset_found
            summary["rollover_seen"] = rollover_found
            if rollover_found:
                exceptions.append({
                    "exception_id": f"REGISTER_ROLLOVER:{serial}",
                    "device_serial": serial,
                    "device_identifier": "",
                    "dtr_name": "",
                    "reason": "CUMULATIVE_REGISTER_ROLLOVER",
                    "evidence": "Register decreased from near 100,000,000 Wh to below 10,000,000 Wh; rollover correction applied",
                    "handling": "Applied 100,000,000 Wh rollover modulus",
                })
            if len(vals) < 2:
                summary["energy_reason"] = "INSUFFICIENT_VALID_READINGS"
            elif reset_found:
                summary["energy_reason"] = "REGISTER_RESET"
            else:
                summary["energy_kwh"] = total_wh / 1000.0
                summary["energy_reason"] = "ROLLOVER_CORRECTED" if rollover_found else "CALCULATED_FROM_CUMULATIVE_DELTAS"

            if duplicate_rows:
                exceptions.append({
                    "exception_id": f"DUPLICATE_READINGS:{serial}",
                    "device_serial": serial,
                    "device_identifier": "",
                    "dtr_name": "",
                    "reason": "EXACT_DUPLICATE_HES_READINGS",
                    "evidence": f"{duplicate_rows} repeated (device_serial, data_timestamp, import_wh) row(s)",
                    "handling": "Deduplicated for metrics; raw database rows retained",
                })

        for row in stream:
            processed += 1
            serial = str(row["device_serial"] or "").strip()
            if current_serial is None:
                current_serial = serial
            if serial != current_serial:
                process_serial(current_serial, serial_rows)
                serial_rows = []
                current_serial = serial
            serial_rows.append(row)
            if processed % 500000 == 0:
                print(f"Scanned {processed:,} HES rows...")
        if current_serial is not None:
            process_serial(current_serial, serial_rows)
        stream.close()

        # Record ambiguous master mappings and serials with no master.
        for identifier, mappings in sorted(by_identifier.items()):
            consumer_mappings = [m for m in mappings if m["meter_type"] != "DT"]
            dtrs = sorted({m["dtr_name"] for m in consumer_mappings})
            serials = sorted({m["device_serial"] for m in consumer_mappings})
            if len(dtrs) > 1 or len(serials) > 1:
                exceptions.append({
                    "exception_id": f"AMBIGUOUS_MASTER:{identifier}",
                    "device_serial": ";".join(serials),
                    "device_identifier": identifier,
                    "dtr_name": ";".join(dtrs),
                    "reason": "DUPLICATE_OR_AMBIGUOUS_MASTER_MAPPING",
                    "evidence": f"{len(consumer_mappings)} consumer master rows; DTRs={dtrs}; serials={serials}",
                    "handling": "Excluded from R2 to avoid multiplying or misattributing consumer energy",
                })

        for serial, summary in sorted(read_summary.items()):
            if serial not in by_serial:
                exceptions.append({
                    "exception_id": f"ORPHAN_HES_SERIAL:{serial}",
                    "device_serial": serial,
                    "device_identifier": "",
                    "dtr_name": "",
                    "reason": "HES_SERIAL_WITHOUT_DEVICE_MASTER",
                    "evidence": f"{len(summary['slots'])} accepted in-window slots; first={summary['first']}; last={summary['last']}",
                    "handling": "Excluded from consumer R1 and DTR output because no authoritative master mapping exists",
                })

        # R1: one row per distinct consumer identifier. Duplicate master rows
        # remain visible in R3; use a unique serial only if the mapping is unambiguous.
        r1 = []
        consumer_ids = sorted(
            identifier for identifier, mappings in by_identifier.items()
            if any(m["meter_type"] != "DT" for m in mappings)
        )
        for identifier in consumer_ids:
            mappings = [m for m in by_identifier[identifier] if m["meter_type"] != "DT"]
            serials = sorted({m["device_serial"] for m in mappings if m["device_serial"]})
            dtrs = sorted({m["dtr_name"] for m in mappings if m["dtr_name"]})
            ambiguous = len(serials) != 1 or len(dtrs) != 1
            serial = serials[0] if len(serials) == 1 else ""
            summary = read_summary.get(serial, {}) if serial else {}
            slots = summary.get("slots", set())
            received = len(slots)
            availability = round(received / expected * 100, 4) if expected else None
            bill = billing.get(identifier, {})
            meter_events = events_by_id.get(identifier, [])
            power_downs = [e for e in meter_events if int(e["event_code"]) == 101]
            restores = [e for e in meter_events if int(e["event_code"]) == 102]
            status = str(bill.get("mdm_connection_status") or "")
            bill_status = str(bill.get("bill_status") or "")
            first = summary.get("first")
            last = summary.get("last")

            if received == expected and not ambiguous:
                reason = "FULLY_COMMUNICATING"
                evidence = "All expected slots present after duplicate/timestamp validation"
            elif received == 0 and (
                bill_status == "Bill Read Not Avlb" or
                (not bill and any(m.get("commissioned_on") for m in mappings))
            ):
                reason = "NEVER_COMMISSIONED"
                evidence = f"accepted_reads=0; billing.bill_status={bill_status or 'NO_BILLING_ROW'}"
            elif received < expected and power_downs:
                reason = "OUTAGE"
                down = power_downs[0]
                restore = next((e for e in restores if e["event_timestamp_ist"] >= down["event_timestamp_ist"]), None)
                evidence = f"event 101 at {down['event_timestamp_ist']}"
                if restore:
                    evidence += f"; event 102 at {restore['event_timestamp_ist']}"
                else:
                    evidence += "; no matching event 102 found in reporting window"
            elif received < expected and status.lower() == "disconnected" and (
                bill_status.lower() == "disconnected" or
                (last is not None and last < end_exclusive - timedelta(days=2))
            ):
                reason = "DISCONNECTED"
                evidence = (
                    f"billing.mdm_connection_status={status}; "
                    f"billing.bill_status={bill_status}; last_read={last}"
                )
            else:
                reason = "UNEXPLAINED"
                evidence = (
                    f"received_blocks={received}/{expected}; first_read={first}; last_read={last}; "
                    f"billing.mdm_connection_status={status or 'NULL'}; bill_status={bill_status or 'NULL'}"
                )

            if ambiguous:
                evidence += f"; ambiguous_master_mappings={len(mappings)}; DTRs={dtrs}; serials={serials}"
                exceptions.append({
                    "exception_id": f"AMBIGUOUS_MASTER_R1:{identifier}",
                    "device_serial": ";".join(serials),
                    "device_identifier": identifier,
                    "dtr_name": ";".join(dtrs),
                    "reason": "DUPLICATE_OR_AMBIGUOUS_MASTER_MAPPING",
                    "evidence": evidence,
                    "handling": "R1 row retained; energy attribution excluded from R2",
                })

            r1.append({
                "device_identifier": identifier,
                "device_serial": serial or ";".join(serials),
                "dtr_name": dtrs[0] if len(dtrs) == 1 else ";".join(dtrs),
                "expected_blocks": expected,
                "received_blocks": received,
                "availability_pct": availability,
                "first_read_ist": first,
                "last_read_ist": last,
                "noncomm_reason": reason,
                "evidence": evidence,
            })

        # R2: energy in from DT cumulative register; energy out from unique,
        # unambiguous consumer serials. Meters with reset/insufficient data are excluded.
        dtr_totals = defaultdict(lambda: {
            "energy_in": None, "energy_out": 0.0, "contributing": 0,
            "excluded": 0, "excluded_reasons": [], "input_reason": "",
        })
        for dtr_name, dt in sorted(dtr_master.items()):
            serial = str(dt["device_serial"])
            summary = read_summary.get(serial, {})
            totals = dtr_totals[dtr_name]
            totals["energy_in"] = summary.get("energy_kwh")
            totals["input_reason"] = summary.get("energy_reason", "NO_DT_READINGS")
            if totals["energy_in"] is None:
                exceptions.append({
                    "exception_id": f"DT_INPUT_INVALID:{dtr_name}",
                    "device_serial": serial,
                    "device_identifier": dt["device_identifier"],
                    "dtr_name": dtr_name,
                    "reason": "DT_INPUT_ENERGY_UNAVAILABLE",
                    "evidence": f"energy_reason={totals['input_reason']}; first={summary.get('first')}; last={summary.get('last')}",
                    "handling": "DTR loss percentage reported as not calculable",
                })

        for identifier in consumer_ids:
            mappings = [m for m in by_identifier[identifier] if m["meter_type"] != "DT"]
            dtrs = sorted({m["dtr_name"] for m in mappings if m["dtr_name"]})
            serials = sorted({m["device_serial"] for m in mappings if m["device_serial"]})
            reason = None
            serial = serials[0] if len(serials) == 1 else None
            dtr = dtrs[0] if len(dtrs) == 1 else None
            summary = read_summary.get(serial, {}) if serial else {}
            if len(dtrs) != 1 or len(serials) != 1:
                reason = "AMBIGUOUS_MASTER_MAPPING"
            elif not summary:
                reason = "NO_ACCEPTED_HES_READINGS"
            elif summary.get("energy_kwh") is None:
                reason = summary.get("energy_reason") or "ENERGY_UNAVAILABLE"
            elif dtr not in dtr_totals:
                reason = "DTR_HAS_NO_DT_MASTER"
            if reason:
                if dtr in dtr_totals:
                    dtr_totals[dtr]["excluded"] += 1
                    dtr_totals[dtr]["excluded_reasons"].append(f"{identifier}:{reason}")
                exceptions.append({
                    "exception_id": f"R2_EXCLUDED:{identifier}",
                    "device_serial": ";".join(serials),
                    "device_identifier": identifier,
                    "dtr_name": ";".join(dtrs),
                    "reason": f"R2_CONSUMER_EXCLUDED:{reason}",
                    "evidence": f"serials={serials}; dtrs={dtrs}; energy_reason={summary.get('energy_reason', 'NO_SUMMARY')}",
                    "handling": "Excluded from DTR consumer output total",
                })
                continue
            dtr_totals[dtr]["energy_out"] += float(summary["energy_kwh"])
            dtr_totals[dtr]["contributing"] += 1

        r2 = []
        for dtr, totals in sorted(dtr_totals.items()):
            energy_in = totals["energy_in"]
            energy_out = totals["energy_out"]
            loss_kwh = energy_in - energy_out if energy_in is not None else None
            loss_pct = (loss_kwh / energy_in * 100.0) if energy_in not in (None, 0) else None
            r2.append({
                "dtr_name": dtr,
                "dt_energy_in_kwh": round(energy_in, 3) if energy_in is not None else None,
                "consumer_energy_out_kwh": round(energy_out, 3),
                "loss_kwh": round(loss_kwh, 3) if loss_kwh is not None else None,
                "loss_pct": round(loss_pct, 3) if loss_pct is not None else None,
                "consumer_meters_contributing": totals["contributing"],
                "consumer_meters_excluded": totals["excluded"],
                "excluded_meter_reasons": " | ".join(sorted(totals["excluded_reasons"])),
                "input_energy_status": totals["input_reason"],
                "loss_over_threshold": bool(loss_pct is not None and loss_pct > threshold),
            })

        # R3 additions for data-quality conflicts and daily-load reconciliation.
        for identifier, mappings in sorted(by_identifier.items()):
            if len(mappings) > 1:
                exceptions.append({
                    "exception_id": f"DUPLICATE_MASTER:{identifier}",
                    "device_serial": ";".join(sorted({m['device_serial'] for m in mappings})),
                    "device_identifier": identifier,
                    "dtr_name": ";".join(sorted({m['dtr_name'] for m in mappings})),
                    "reason": "DUPLICATE_MASTER_ROWS",
                    "evidence": f"{len(mappings)} device_info rows for the same device_identifier",
                    "handling": "Mappings are not blindly joined; ambiguous consumer energy excluded from R2",
                })
        for identifier, daily_rows in sorted(daily_by_id.items()):
            estimated = [r for r in daily_rows if bool(r["is_estimated"])]
            if estimated:
                exceptions.append({
                    "exception_id": f"ESTIMATED_DAILY_LOAD:{identifier}",
                    "device_serial": "",
                    "device_identifier": identifier,
                    "dtr_name": "",
                    "reason": "MDMS_DAILY_LOAD_CONTAINS_ESTIMATED_DAYS",
                    "evidence": "; ".join(f"{r['load_date']}={r['total_import_kwh']} kWh (estimated)" for r in estimated[:5]),
                    "handling": "MDMS estimates retained as reconciliation evidence; not used as authoritative R2 energy",
                })

        # Stable deduplication: the same finding can be reached through R1 and R2.
        unique_exceptions = {}
        for item in exceptions:
            unique_exceptions[item["exception_id"]] = item
        r3 = [unique_exceptions[k] for k in sorted(unique_exceptions)]

        write_csv(
            output_dir / "R1_communication_report.csv",
            ["device_identifier", "device_serial", "dtr_name", "expected_blocks",
             "received_blocks", "availability_pct", "first_read_ist", "last_read_ist",
             "noncomm_reason", "evidence"],
            r1,
        )
        write_csv(
            output_dir / "R2_dtr_energy_balance.csv",
            ["dtr_name", "dt_energy_in_kwh", "consumer_energy_out_kwh", "loss_kwh",
             "loss_pct", "consumer_meters_contributing", "consumer_meters_excluded",
             "excluded_meter_reasons", "input_energy_status", "loss_over_threshold"],
            r2,
        )
        write_csv(
            output_dir / "R3_exceptions_register.csv",
            ["exception_id", "device_serial", "device_identifier", "dtr_name",
             "reason", "evidence", "handling"],
            r3,
        )

        print("\nReports generated:")
        print(f"R1 consumer meters: {len(r1):,}")
        print(f"R2 DTRs: {len(r2):,}")
        print(f"R3 exceptions: {len(r3):,}")
        print(f"Output directory: {output_dir}")
        print("Files: R1_communication_report.csv, R2_dtr_energy_balance.csv, R3_exceptions_register.csv")
        print("\nImportant: inspect R2 for excluded meters and validate energy totals before submission.")
    finally:
        conn.close()


if __name__ == "__main__":
    main()
