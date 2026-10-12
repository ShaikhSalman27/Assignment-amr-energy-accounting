# AMR Energy Accounting & Non-Communication RCA

## Overview

This project generates communication, DTR energy-balance, and data-quality exception reports for September 2026.

The implementation uses **MySQL 8.0** instead of the PostgreSQL setup shown in the original brief. Database setup and SQL syntax are therefore MySQL-specific.

## Prerequisites

- Python 3.11 or newer
- MySQL Server 8.0
- MySQL Workbench (optional)
- Python package: `mysql-connector-python`

Install the Python dependency:

```powershell
python -m pip install mysql-connector-python
```

## Input data and database

Generate the full synthetic dataset:

```powershell
python generate_dataset.py --out .\data_full
```

Create the MySQL tables using `schema_mysql.sql` in MySQL Workbench. Import the five generated CSV files into their corresponding tables.

Configure the MySQL connection and credentials as required by `src/report_pipeline.py`. Do not commit passwords or secrets.

## Configuration

- `config/pipeline_config.json`: development configuration.
- `config/pipeline_config_full.json`: full-dataset configuration.
- `src/validate_inputs.py` currently selects the full-dataset configuration.

The reporting window is September 1, 2026 00:00 IST through October 1, 2026 00:00 exclusive. The expected interval is 30 minutes, giving 1,440 expected blocks per meter.

## Run the pipeline

From the project root:

```powershell
python src/validate_inputs.py
python src/pipeline.py
python src/report_pipeline.py
```

The chunk pipeline reads HES data in batches, writes chunk part files, and maintains a checkpoint. If processing is interrupted, run `python src/pipeline.py` again to continue from the recorded checkpoint.

The reporting script connects to MySQL and creates the three CSV reports.

## Output locations

- `outputs_full/blockload_parts/`: chunk output files.
- `checkpoints_full/blockload_checkpoint.json`: pipeline checkpoint.
- `outputs_full/reports/R1_communication_report.csv`: R1 communication report.
- `outputs_full/reports/R2_dtr_energy_balance.csv`: R2 DTR energy balance.
- `outputs_full/reports/R3_exceptions_register.csv`: R3 exception register.

## Idempotency and resume verification

A completed pipeline rerun reported 571 chunks and 2,853,458 source rows. A comparison of the chunk-part filenames, sizes, and SHA-256 hashes before and after a no-op rerun showed no differences.

One earlier checkpoint update encountered a Windows `PermissionError` and required manual checkpoint recovery. Therefore, an uninterrupted Ctrl+C kill-and-resume test at 60% has not yet been demonstrated. Do not interpret the no-op rerun as proof of that separate requirement.

## Operations summary

- The full HES dataset contains 2,853,458 rows.
- R1 classifies 1,975 consumer meters.
- R1 classified 1,649 meters as fully communicating.
- R1 classified 40 as outage, 20 as disconnected, 40 as never commissioned, and 226 as unexplained.
- R2 reports energy balance for 20 DTRs.
- Three DTRs exceed the 15% loss threshold: DTR-02, DTR-03, and DTR-17.
- R3 records 8,296 possible timestamp-shift cases; this is not proof of a confirmed timezone defect.
- R3 records 1,960 exact duplicate-reading exceptions and 1,585 estimated-day exceptions.
- Ambiguous mappings, resets, and out-of-window readings require explicit handling before drawing operational conclusions.

## Actual 60% kill-and-resume test

The full-dataset pipeline was tested using separate test output and
checkpoint directories to protect the final reports.

The pipeline was interrupted with Ctrl+C after chunk 352:

```text
Saved chunk 350: 1,750,000 rows total
Saved chunk 351: 1,755,000 rows total
Saved chunk 352: 1,760,000 rows total
KeyboardInterrupt
```

After restarting, the actual output began:

```text
Resuming after completed chunk 352.
Saved chunk 353: 1,765,000 rows total
```

The pipeline then completed all 571 chunks and processed 2,853,458
source rows. The test used `outputs_resume_test` and
`checkpoints_resume_test`; the final report outputs were kept separate.
