#!/usr/bin/env python3
"""
Synthetic smart-metering dataset for the Polaris data-forensics assignment.

Pure stdlib, deterministic. Produces 5 CSVs that mimic the shape (and the
failure modes) of a real HES / MDMS / billing stack.

    python3 generate_dataset.py --out ./data
    python3 generate_dataset.py --out ./data --meters 400 --days 10   # smoke run

Nothing here is production data. Any resemblance to a working pipeline is
intentional; any resemblance to a clean one is not.
"""

import argparse
import csv
import os
import random
from datetime import datetime, timedelta

SEED = 20261010
WINDOW_START = datetime(2026, 9, 1, 0, 0, 0)  # literal IST, naive
IST_OFFSET = timedelta(hours=5, minutes=30)
METERS_PER_DTR = 100

# hour-of-day shape for a residential feeder (relative, not absolute)
HOUR_SHAPE = [
    0.45, 0.40, 0.38, 0.37, 0.38, 0.45, 0.60, 0.75,
    0.85, 0.80, 0.75, 0.72, 0.78, 0.80, 0.78, 0.75,
    0.80, 0.95, 1.20, 1.40, 1.35, 1.10, 0.80, 0.55,
]


def ts_str(dt):
    return dt.strftime("%Y-%m-%d %H:%M:%S")


def build_meters(rng, n_meters, n_dtrs):
    """device_info rows + per-meter behaviour profile."""
    meters = []
    for i in range(n_meters):
        serial_num = 900000000 + i
        dtr_idx = i // METERS_PER_DTR
        meters.append(
            {
                "idx": i,
                "device_identifier": "GPM%d" % serial_num,
                "device_serial": str(serial_num),
                "dtr": "DTR-%02d (by AMISP)" % (dtr_idx + 1),
                "dtr_idx": dtr_idx,
                "lat": round(26.75 + dtr_idx * 0.011 + rng.uniform(-0.004, 0.004), 6),
                "lon": round(82.13 + dtr_idx * 0.009 + rng.uniform(-0.004, 0.004), 6),
                "profile": "normal",
                "gap_blocks": set(),
                "offline_from": None,
                "sticky_disconnect": False,
                "register_reset_at": None,
                "rollover": False,
                "in_device_info": True,
                "in_blockload": True,
                "serial_matches_tail": True,
            }
        )

    pool = [m for m in meters if m["dtr_idx"] < n_dtrs]
    rng.shuffle(pool)
    cur = 0

    def take(k):
        nonlocal cur
        chunk = pool[cur : cur + k]
        cur += k
        return chunk

    scale = max(1, len(pool) // 2000)

    # meters that simply never report (commissioned on paper only)
    for m in take(40 * scale):
        m["profile"] = "never_reported"
        m["in_blockload"] = False

    # meters reporting to HES but absent from the MDMS master
    for m in take(25 * scale):
        m["profile"] = "orphan"
        m["in_device_info"] = False

    # non-comm explained by a paired outage (101 -> 102)
    for m in take(40 * scale):
        m["profile"] = "outage_gap"

    # non-comm explained by a field disconnection
    for m in take(20 * scale):
        m["profile"] = "disconnected"

    # non-comm with no explanation anywhere - the real finding
    for m in take(20 * scale):
        m["profile"] = "unexplained_noncomm"

    # perfectly live, but billing still carries a stale "Disconnected" state
    for m in take(100 * scale):
        m["sticky_disconnect"] = True

    # patchy RF comm
    for m in take(200 * scale):
        m["profile"] = "patchy"

    # meter replaced mid-month: cumulative register restarts near zero
    for m in take(12 * scale):
        m["register_reset_at"] = rng.uniform(0.35, 0.75)

    # register rolls over the 8-digit ceiling
    for m in take(5 * scale):
        m["rollover"] = True

    # master-data drift: HES serial is not the numeric tail of the MDMS id
    for m in take(15 * scale):
        m["serial_matches_tail"] = False
        m["device_serial"] = str(700000000 + m["idx"])

    return meters


def assign_gaps(rng, meters, n_blocks, blocks_per_day):
    for m in meters:
        if m["profile"] == "patchy":
            n_missing = int(n_blocks * rng.uniform(0.02, 0.10))
            m["gap_blocks"] = set(rng.sample(range(n_blocks), n_missing))
        elif m["profile"] == "outage_gap":
            start_day = rng.randint(3, max(3, (n_blocks // blocks_per_day) - 5))
            length_days = rng.randint(1, 3)
            s = start_day * blocks_per_day + rng.randint(0, blocks_per_day - 1)
            e = min(n_blocks, s + length_days * blocks_per_day)
            m["gap_blocks"] = set(range(s, e))
            m["outage_span"] = (s, e)
        elif m["profile"] in ("disconnected", "unexplained_noncomm"):
            s = rng.randint(blocks_per_day * 5, max(blocks_per_day * 5, n_blocks - blocks_per_day * 2))
            m["offline_from"] = s
            m["gap_blocks"] = set(range(s, n_blocks))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default="./data")
    ap.add_argument("--meters", type=int, default=2000)
    ap.add_argument("--days", type=int, default=30)
    ap.add_argument("--block-minutes", type=int, default=30)
    args = ap.parse_args()

    rng = random.Random(SEED)
    os.makedirs(args.out, exist_ok=True)

    blocks_per_day = (24 * 60) // args.block_minutes
    n_blocks = blocks_per_day * args.days
    n_dtrs = max(1, args.meters // METERS_PER_DTR)
    meters = build_meters(rng, args.meters, n_dtrs)
    assign_gaps(rng, meters, n_blocks, blocks_per_day)

    # three DTRs bleed energy; the rest are within normal technical loss
    high_loss = set(rng.sample(range(n_dtrs), min(3, n_dtrs)))
    dtr_loss = {
        d: (rng.uniform(0.22, 0.31) if d in high_loss else rng.uniform(0.03, 0.08))
        for d in range(n_dtrs)
    }
    dtr_block_wh = [[0.0] * n_blocks for _ in range(n_dtrs)]

    bl_path = os.path.join(args.out, "hes_blockload.csv")
    dl_path = os.path.join(args.out, "mdms_daily_load.csv")
    ev_path = os.path.join(args.out, "meter_events.csv")
    bp_path = os.path.join(args.out, "billing_profile.csv")
    di_path = os.path.join(args.out, "device_info.csv")

    bl_f = open(bl_path, "w", newline="")
    dl_f = open(dl_path, "w", newline="")
    ev_f = open(ev_path, "w", newline="")
    bp_f = open(bp_path, "w", newline="")
    bl = csv.writer(bl_f)
    dl = csv.writer(dl_f)
    ev = csv.writer(ev_f)
    bp = csv.writer(bp_f)

    bl.writerow(["device_serial", "data_timestamp", "import_wh", "voltage_v", "current_a"])
    dl.writerow(["device_identifier", "load_date", "total_import_kwh", "is_estimated"])
    ev.writerow(["device_identifier", "event_code", "event_timestamp_ist", "created_at_utc"])
    bp.writerow(
        [
            "device_identifier",
            "billing_month",
            "opening_kwh",
            "closing_kwh",
            "mdm_connection_status",
            "bill_status",
        ]
    )

    block_times = [WINDOW_START + timedelta(minutes=args.block_minutes * b) for b in range(n_blocks)]

    for m in meters:
        if not m["in_blockload"]:
            # still gets a master row and a billing row; never a reading
            if m["in_device_info"]:
                bp.writerow(
                    [m["device_identifier"], "2026-09", 0, 0, "Connected", "Bill Read Not Avlb"]
                )
            continue

        cum = float(rng.randint(120000, 880000))
        if m["rollover"]:
            cum = 99_880_000.0
        base = rng.uniform(0.06, 0.55)  # kWh per block at shape=1.0
        reset_block = (
            int(m["register_reset_at"] * n_blocks) if m["register_reset_at"] else None
        )
        day_kwh = 0.0
        day_has_gap = False
        emitted_rows = 0

        for b in range(n_blocks):
            t = block_times[b]
            shape = HOUR_SHAPE[t.hour]
            wh = base * shape * 1000.0 * rng.uniform(0.85, 1.15)
            cum += wh
            if m["rollover"] and cum > 99_999_999:
                cum -= 100_000_000
            if reset_block is not None and b == reset_block:
                cum = float(rng.randint(40, 900))  # replacement meter, fresh register
            dtr_block_wh[m["dtr_idx"]][b] += wh

            missing = b in m["gap_blocks"]
            if missing:
                day_has_gap = True
            else:
                bl.writerow(
                    [
                        m["device_serial"],
                        ts_str(t),
                        round(cum, 1),
                        round(rng.uniform(198, 248), 1),
                        round(wh / 230.0 / (args.block_minutes / 60.0), 2),
                    ]
                )
                emitted_rows += 1
                day_kwh += wh / 1000.0

                # exact duplicate row (HES replay)
                if rng.random() < 0.015:
                    bl.writerow(
                        [
                            m["device_serial"],
                            ts_str(t),
                            round(cum, 1),
                            round(rng.uniform(198, 248), 1),
                            round(wh / 230.0 / (args.block_minutes / 60.0), 2),
                        ]
                    )
                # same reading re-ingested after a bad UTC->IST conversion
                if rng.random() < 0.003:
                    bl.writerow(
                        [
                            m["device_serial"],
                            ts_str(t + IST_OFFSET),
                            round(cum, 1),
                            round(rng.uniform(198, 248), 1),
                            round(wh / 230.0 / (args.block_minutes / 60.0), 2),
                        ]
                    )
                # corrupt clock on the meter
                if rng.random() < 0.0002:
                    bad = rng.choice(
                        [datetime(1970, 1, 1, 5, 30), datetime(2099, 12, 31, 23, 30)]
                    )
                    bl.writerow(
                        [m["device_serial"], ts_str(bad), round(cum, 1), 0.0, 0.0]
                    )

            if (b + 1) % blocks_per_day == 0:
                load_date = t.date().isoformat()
                if day_kwh > 0 or not day_has_gap:
                    est = day_has_gap or rng.random() < 0.05
                    val = day_kwh * (rng.uniform(1.02, 1.18) if est else 1.0)
                    dl.writerow(
                        [m["device_identifier"], load_date, round(val, 3), str(est).lower()]
                    )
                day_kwh = 0.0
                day_has_gap = False

        # ---- events -------------------------------------------------------
        if m["profile"] == "outage_gap" and m.get("outage_span"):
            s, e = m["outage_span"]
            t_start = block_times[s]
            ev.writerow(
                [m["device_identifier"], 101, ts_str(t_start), ts_str(t_start - IST_OFFSET)]
            )
            if e < n_blocks and rng.random() < 0.85:  # 15% never get their restore event
                t_end = block_times[e]
                ev.writerow(
                    [m["device_identifier"], 102, ts_str(t_end), ts_str(t_end - IST_OFFSET)]
                )
        for _ in range(rng.randint(0, 4)):  # ambient voltage / tamper noise
            b = rng.randrange(n_blocks)
            code = rng.choice([9, 10, 203, 204, 207, 208])
            t = block_times[b]
            ev.writerow([m["device_identifier"], code, ts_str(t), ts_str(t - IST_OFFSET)])

        # ---- billing ------------------------------------------------------
        if m["in_device_info"]:
            opening = round(rng.uniform(500, 9000), 2)
            consumed = round(max(0.0, emitted_rows * base * 0.5 * rng.uniform(0.8, 1.2)), 2)
            closing = round(opening + consumed, 2)
            if m["register_reset_at"]:
                closing = round(consumed * 0.1, 2)  # reads lower than opening after swap
            status = "Disconnected" if (m["sticky_disconnect"] or m["profile"] == "disconnected") else "Connected"
            bill_status = (
                "Disconnected"
                if m["profile"] == "disconnected"
                else ("Bill Read Not Avlb" if m["profile"] in ("unexplained_noncomm", "never_reported") else "Billed")
            )
            bp.writerow(
                [m["device_identifier"], "2026-09", opening, closing, status, bill_status]
            )

    # ---- DT (substation-side) meters ---------------------------------------
    for d in range(n_dtrs):
        cum = float(rng.randint(2_000_000, 4_000_000))
        loss = dtr_loss[d]
        dt_id = "DT-%02d" % (d + 1)
        dt_serial = str(800000000 + d)
        day_kwh = 0.0
        for b in range(n_blocks):
            t = block_times[b]
            wh = dtr_block_wh[d][b] / (1.0 - loss)
            cum += wh
            bl.writerow(
                [dt_serial, ts_str(t), round(cum, 1), round(rng.uniform(205, 245), 1), round(wh / 415.0, 2)]
            )
            day_kwh += wh / 1000.0
            if (b + 1) % blocks_per_day == 0:
                dl.writerow([dt_id, t.date().isoformat(), round(day_kwh, 3), "false"])
                day_kwh = 0.0

    for f in (bl_f, dl_f, ev_f, bp_f):
        f.close()

    # ---- master data --------------------------------------------------------
    with open(di_path, "w", newline="") as f:
        di = csv.writer(f)
        di.writerow(
            [
                "device_identifier",
                "device_serial",
                "img_serial_number",
                "dtr_name",
                "latitude",
                "longitude",
                "meter_type",
                "commissioned_on",
            ]
        )
        dup_candidates = [m for m in meters if m["in_device_info"]]
        rng.shuffle(dup_candidates)
        dup_set = {m["device_identifier"] for m in dup_candidates[: max(1, 6 * max(1, args.meters // 2000))]}
        for m in meters:
            if not m["in_device_info"]:
                continue
            row = [
                m["device_identifier"],
                m["device_serial"],
                "IMG%07d" % (4000000 + m["idx"] // 50),
                m["dtr"],
                m["lat"],
                m["lon"],
                "CONSUMER",
                "2026-07-%02d" % rng.randint(1, 28),
            ]
            di.writerow(row)
            if m["device_identifier"] in dup_set:
                other = "DTR-%02d (by AMISP)" % (((m["dtr_idx"] + 1) % n_dtrs) + 1)
                di.writerow(row[:3] + [other] + row[4:])
        for d in range(n_dtrs):
            di.writerow(
                [
                    "DT-%02d" % (d + 1),
                    str(800000000 + d),
                    "",
                    "DTR-%02d (by AMISP)" % (d + 1),
                    round(26.75 + d * 0.011, 6),
                    round(82.13 + d * 0.009, 6),
                    "DT",
                    "2026-06-15",
                ]
            )

    for p in (di_path, bl_path, dl_path, ev_path, bp_path):
        print("%-28s %8.1f MB" % (os.path.basename(p), os.path.getsize(p) / 1e6))


if __name__ == "__main__":
    main()
