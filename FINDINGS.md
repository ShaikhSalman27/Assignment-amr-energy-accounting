### Finding: Conflicting Consumer-to-DTR Master Mappings

**Issue:** The `device_info` master contains six consumer IDs mapped to two different DTRs each.

**Quantified impact (development dataset):**
- 6 affected consumer IDs
- 12 master records across these IDs
- 6 conflicting duplicate records beyond one record per consumer
- The same device serial and image serial appear under two different DTR assignments.

**Evidence:** The duplicate-mapping SQL query returned the following examples:

| Consumer ID | Conflicting DTRs |
|---|---|
| GPM900000004 | DTR-01, DTR-02 |
| GPM900000126 | DTR-02, DTR-03 |
| GPM900000132 | DTR-02, DTR-03 |
| GPM900000193 | DTR-02, DTR-03 |
| GPM900000310 | DTR-01, DTR-04 |
| GPM900000355 | DTR-01, DTR-04 |

**Handling:** Do not arbitrarily select one DTR mapping. Flag conflicting consumer IDs, exclude them from definitive DTR-level energy attribution until the mapping is resolved, and report the excluded count separately.
### F-02 Exact Duplicate HES Readings in Full Dataset

**Impact:** The R3 report contains 1,960 `EXACT_DUPLICATE_HES_READINGS` exception records. If repeated readings are counted more than once, they can distort received-block counts or cumulative-register delta calculations. The total energy impact has not been separately quantified.

**Evidence — SQL used:**

```sql
SELECT device_serial, data_timestamp, import_wh,
       COUNT(*) AS duplicate_count
FROM hes_blockload
GROUP BY device_serial, data_timestamp, import_wh
HAVING COUNT(*) > 1
ORDER BY duplicate_count DESC
LIMIT 5;
```

**Actual rows from MySQL:**

| device_serial | data_timestamp | import_wh | duplicate_count |
|---|---|---:|---:|
| 900001837 | 2026-09-24 03:30:00 | 474515.0 | 2 |
| 900001837 | 2026-09-24 21:00:00 | 479996.8 | 2 |
| 900001837 | 2026-09-25 15:30:00 | 484506.5 | 2 |
| 900001837 | 2026-09-26 00:00:00 | 487665.9 | 2 |
| 900001837 | 2026-09-26 05:00:00 | 488393.2 | 2 |

**Handling:** The reporting pipeline deduplicates readings for metric calculations while retaining raw database rows. The duplicate exception remains documented in R3.

### F-03 Possible 330-Minute Timestamp Shift

**Impact:** The R3 report contains 8,296 `POSSIBLE_IST_UTC_SHIFT_PLUS_330_MIN` exception records. If shifted readings are treated as independent observations, they may affect communication availability and cumulative-register analysis. The exact impact on R1/R2 has not been independently quantified.

**Evidence — SQL used:**

```sql
SELECT
    a.device_serial,
    a.data_timestamp AS timestamp_later,
    b.data_timestamp AS timestamp_earlier,
    a.import_wh
FROM hes_blockload a
JOIN hes_blockload b
  ON a.device_serial = b.device_serial
 AND a.import_wh = b.import_wh
 AND b.data_timestamp = DATE_SUB(a.data_timestamp, INTERVAL 330 MINUTE)
WHERE a.data_timestamp >= '2026-09-01 00:00:00'
  AND a.data_timestamp <  '2026-10-01 00:00:00'
LIMIT 5;
```

**Actual rows from MySQL:**

| device_serial | timestamp_later | timestamp_earlier | import_wh |
|---|---|---|---:|
| 700000160 | 2026-09-06 19:00:00 | 2026-09-06 13:30:00 | 842906.6 |
| 700000160 | 2026-09-17 14:00:00 | 2026-09-17 08:30:00 | 1051926.6 |
| 700000160 | 2026-09-21 23:30:00 | 2026-09-21 18:00:00 | 1137863.1 |
| 700000160 | 2026-09-24 02:30:00 | 2026-09-23 21:00:00 | 1181137.8 |
| 700000160 | 2026-09-28 07:30:00 | 2026-09-28 02:00:00 | 1262184.7 |

**Handling:** The pipeline records these as possible timestamp-shift exceptions and excludes probable shifted duplicates from its accepted metric calculations. The source timezone semantics must be verified before calling this a confirmed timezone defect.
