# AMR Energy Accounting & Non-Communication RCA

## 1. Objective and scope

This specification defines the rules for producing the September 2026 communication report (R1), DTR energy balance (R2), and exceptions register (R3). The reporting window is 2026-09-01 00:00:00 through 2026-09-30 23:59:59 IST. All reported results must be reproducible from the supplied dataset.

## 2. Data sources and grain

The pipeline uses five PostgreSQL tables:

- `device_info`: meter master data, meter-to-DTR mapping, serial numbers, and meter type.
- `hes_blockload`: cumulative energy register readings with timestamps, voltage, and current. Each row represents a received reading; duplicates may exist.
- `mdms_daily_load`: daily energy deltas and an estimated-reading flag, at meter-day grain.
- `meter_events`: meter events with an IST event timestamp and a separate UTC creation timestamp. Event 101 means power-down; event 102 means power-restore.
- `billing_profile`: September 2026 billing and connection status, at meter-month grain.

Consumer meters are records whose `meter_type` is not `DT`. DT meters represent the input-side energy meter for a DTR.

## 3. Join keys and timestamp handling

Consumer HES readings will be mapped to master records using `device_info.device_serial = hes_blockload.device_serial`, with `device_identifier` used to connect the master to billing, daily load, and events. DT readings will be mapped using the DT master record and its device serial. DTR energy output will be grouped by the master-data DTR mapping.

The blockload timestamp is a naive timestamp representing literal IST. `event_timestamp_ist` is also literal IST, while `created_at_utc` is UTC. These fields must not be treated as interchangeable. Reporting-window filters use the literal IST timestamps.

Duplicate master mappings, unmatched serials, duplicate readings, and ambiguous mappings will be detected and recorded rather than silently multiplied in joins.

## 4. R1 — Communication report

The expected schedule is one reading every 30 minutes. The default full-month denominator is 1,440 expected slots per meter. Expected slots are generated from the reporting window, not inferred from the number of received rows.

Received blocks are the count of distinct expected half-hour slots containing at least one accepted reading after duplicate and timestamp validation. Availability is:

`availability_pct = received_blocks / expected_blocks * 100`

First and last read are the minimum and maximum accepted timestamps within the reporting window. Readings outside the window do not count.

Each consumer meter receives one classification:

- `FULLY_COMMUNICATING`: every expected slot has an accepted reading.
- `OUTAGE`: a missing interval is supported by power-down/power-restore events (101/102).
- `DISCONNECTED`: a sustained communication gap is supported by consistent disconnection evidence; billing status alone is insufficient.
- `NEVER_COMMISSIONED`: no accepted reads exist during the reporting window and available master/billing evidence supports a never-reporting meter. This is a data-based operational classification, not proof of physical commissioning history.
- `UNEXPLAINED`: communication is incomplete and the available evidence does not support another classification.

Classification precedence and conflicting evidence will be documented in the implementation. Every non-fully-communicating row must include an evidence field referencing actual identifiers, timestamps, or source fields. A classification unsupported by the available data must be marked as uncertain in the evidence.

## 5. R2 — DTR energy balance

For each DTR, calculate input energy from its DT meter and output energy from eligible consumer meters assigned to that DTR.

`loss_kwh = energy_in_kwh - energy_out_kwh`

`loss_pct = loss_kwh / energy_in_kwh * 100`

DTRs with loss above 15% will be flagged. A zero or invalid input-energy denominator will be reported as not calculable, not as zero loss.

The HES register `import_wh` is cumulative, so consumption must be derived from consecutive valid readings after deduplication and chronological ordering. Valid register rollover must be handled explicitly. Register resets, implausible negative deltas, missing intervals, ambiguous mappings, and insufficient readings must not be treated as ordinary consumption.

MDMS daily deltas and estimated flags will be used for reconciliation and supporting evidence. The pipeline will document which source is authoritative for the final R2 calculation and how incomplete intervals affect eligibility. Each DTR must report the number of contributing meters and excluded meters, with exclusion reasons.

## 6. R3 — Exceptions register

Record every meter or record that cannot be accounted for cleanly, including orphan readings, duplicate master mappings, unmatched serial numbers, duplicate or shifted timestamps, register resets, rollover anomalies, unexplained gaps, conflicting billing status, estimated or missing daily data, and invalid energy calculations.

Each exception must contain a stable identifier, exception reason, relevant source record identifiers or values, and the handling decision. A meter may appear in both R1 and R3.

## 7. Assumptions and exclusions

The default reporting interval is 30 minutes, as specified by the supplied generator and assignment. The full dataset must be used for final numbers; reduced datasets are for development only.

The supplied data is synthetic and does not independently prove physical meter commissioning, tampering, or the real-world cause of every failure. Event codes other than 101 and 102 are not treated as outage evidence for this task.

No energy will be imputed solely to make a DTR balance complete. Ambiguous or invalid records will be excluded from affected calculations only under documented rules and will remain visible in the exceptions register. All thresholds and reporting-window settings must be configurable outside the pipeline code.

## 8. Validation and reproducibility

The final outputs must be generated end-to-end from a clean checkout. Processing must support chunked, resumable execution without duplicate output, and repeated runs must produce byte-identical reports. SQL findings must include actual rows from the generated data. Query-performance changes must be supported by `EXPLAIN (ANALYZE, BUFFERS)` evidence. Unverified AI-generated claims must not be presented as findings.