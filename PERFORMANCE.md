# Performance Analysis

## Environment

- Database: MySQL 8.0
- Table: `hes_blockload`
- Approximate rows scanned: 2.85 million
- Query purpose: Read HES blockload data in report-processing order.

## Before optimization

Query:

```sql
EXPLAIN ANALYZE
SELECT device_serial, data_timestamp, import_wh, voltage_v, current_a
FROM hes_blockload
ORDER BY device_serial, data_timestamp, import_wh;
```

Observed plan:

- Table scan on `hes_blockload`.
- A separate Sort node ordered the rows by
  `device_serial`, `data_timestamp`, and `import_wh`.
- Actual Sort timing: approximately 11.563–12.254 seconds.
- Approximately 2.85 million rows were processed.

The separate sort was the main avoidable operation. MySQL had to read the table and then order the results.

## Change made

Created a composite covering index:

```sql
CREATE INDEX idx_hes_report_order
ON hes_blockload (
    device_serial,
    data_timestamp,
    import_wh,
    voltage_v,
    current_a
);
```

Index creation took 22.937 seconds in this run.

## After optimization

The same `EXPLAIN ANALYZE` query returned:

```text
Covering index scan on hes_blockload
using idx_hes_report_order
(actual time=0.0403..5102 rows=2.85e+6 loops=1)
```

The plan no longer showed a separate Sort node. The covering index contains the columns needed by the query, allowing MySQL to read them in index order without a separate table lookup for each row.

## Measured comparison

| Measurement | Before | After |
|---|---:|---:|
| Plan | Table scan + Sort | Covering index scan |
| Approximate final-row time | 12.254 s | 5.102 s |
| Rows returned | 2.85 million | 2.85 million |

Observed execution time decreased by approximately 58.3%, or about 2.4 times faster in these runs. Timings depend on hardware, cache state, and database load.

## Trade-offs and limitations

The index took 22.937 seconds to create and consumes additional disk space. Its creation time is a one-time setup cost, not part of each report query.

This test uses MySQL 8.0, rather than the PostgreSQL environment described in the original assignment. The execution plans and measurements above are from MySQL and are not PostgreSQL results.

The measured query is the ordered HES scan used by the report pipeline. This benchmark demonstrates the effect of the index on that query; it does not by itself prove the total end-to-end report pipeline became 58.3% faster.
