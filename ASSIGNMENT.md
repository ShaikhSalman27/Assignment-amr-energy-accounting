# Take-home: AMR energy accounting & non-communication RCA

**Candidate:** Mahmmadsalman Shekh
**Timebox:** 6–8 hours of work. Submit within 3 calendar days of receiving this.
**Submit:** one git repo (public or zipped) containing everything listed under *Deliverables*.

---

## 0. What this role actually is

You will not be asked to train models. You will be handed a question like *"why is DTR-07 showing 28% loss"* or
*"why did 4,000 meters stop communicating last Tuesday"*, pointed at three systems that disagree with each other,
and expected to come back with an answer that survives being challenged — plus the script that reproduces it.

AI is the tool we use to go fast. This assignment tests whether you can go fast **without** shipping an answer the
AI invented. Using Claude / Gemini / Copilot is required, not tolerated. Pasting their output unverified is the one
way to fail outright.

---

## 1. Setup

```bash
python3 generate_dataset.py --out ./data          # ~2.9M blockload rows, ~150 MB, <1 min
createdb amr_assignment
psql amr_assignment -v data_dir=$PWD/data -f schema.sql
```

Postgres is expected. If you genuinely cannot run Postgres, DuckDB is acceptable — say so in the README and the
performance section (Part D) still applies.

Use `--meters 400 --days 6` while developing. Final numbers must come from the full default dataset.

### The five tables

| Table | What it is |
|---|---|
| `device_info` | MDMS master: meter ↔ DTR ↔ location |
| `hes_blockload` | Head-end 30-minute reads. `import_wh` is a **cumulative** register, not consumption |
| `mdms_daily_load` | MDMS day aggregate, `total_import_kwh` is a **delta** |
| `meter_events` | Meter/DCU events. 101 = power-down, 102 = power-restore, others are noise for this task |
| `billing_profile` | September 2026 billing state |

Meters whose `meter_type = 'DT'` are substation-side meters, one per DTR. Everything else is a consumer meter.

---

## 2. The ask

For the window **2026-09-01 00:00 to 2026-09-30 23:59 IST**, produce:

**R1 — Per-meter communication report.** One row per consumer meter: expected blocks, received blocks,
communication availability %, first and last read, and a `noncomm_reason` classified as one of
`FULLY_COMMUNICATING` / `OUTAGE` / `DISCONNECTED` / `NEVER_COMMISSIONED` / `UNEXPLAINED`. Every non-`FULLY_COMMUNICATING`
row must carry an `evidence` column naming the actual row(s) that justify the classification (event id + timestamp,
billing field + value, last read timestamp — whatever applies).

**R2 — DTR energy balance.** Per DTR: DT-meter energy in, sum of consumer energy out, loss kWh, loss %, number of
consumer meters contributing, and number excluded (with reason). Flag DTRs above 15% loss.

**R3 — Exceptions register.** Every meter you could not account for cleanly, with the reason and the evidence.
A meter can appear in R3 and in R1.

Output as one `.xlsx` with three sheets, or three `.csv` files. Your call — defend it in one line.

### Deliberately not specified

Three things in the ask above are ambiguous. We know. Find them, decide, and write your decision and its
justification into the spec (Part A). Asking us is also a valid move — but a reasoned assumption beats a blocked
afternoon.

---

## 3. Deliverables

### Part A — Spec before code (`docs/specs/amr-energy-accounting.md`)

Written **first**, committed **before** your first pipeline commit — we will read `git log` to check.
Must cover: data sources and their grain, join keys, the exact definition of every metric in R1/R2 (especially
availability % — state the denominator), every assumption you are making, and what you deliberately excluded.
One page is enough. Prose, not bullets-as-filler.

### Part B — The pipeline (`src/`)

Runnable end-to-end from a clean checkout with one documented command.

Hard requirements:
- **Resumable.** It processes in chunks and writes per-chunk part files. Kill it at 60% (`Ctrl-C`), restart it,
  and it must resume — not restart, not duplicate. Show this in the README with the actual terminal output of a
  kill-and-resume run.
- **Idempotent.** Running it twice produces byte-identical output.
- Config (DSN, window, thresholds) out of the code.
- No silent `except: pass`. A row you cannot process goes to the exceptions register with a reason.

### Part C — `FINDINGS.md`

The dataset is dirty on purpose. Every defect you find gets an entry in this format:

```
### F-01 <one-line title>
Impact:   what it does to R1/R2/R3 if you miss it (quantified — "inflates DTR-04 consumption by 1.4%")
Evidence: the SQL you ran, and 2-5 ACTUAL ROWS from the output, pasted
Handling: what your pipeline does about it
```

An entry with an explanation but no pasted rows scores zero. We want the rows.

There are more defects planted than most people find. Finding all of them is not the bar; the bar is that every
one you *claim* is proved from raw data, and that the ones you did not handle are listed as known gaps rather than
quietly ignored.

### Part D — `PERFORMANCE.md`

Take your single heaviest query. Show `EXPLAIN (ANALYZE, BUFFERS)` before, what you changed and why, and the same
plan after. Name the node that was actually costing you. "Added an index, it got faster" is not an answer —
we want to see that you read the plan.

### Part E — `AI_LOG.md`

The most important file in the submission.

- Which assistant(s), for what.
- **Verbatim** the 3 prompts that did the most work. Not cleaned up.
- At least **two** cases where the AI gave you a confident, plausible, wrong answer on this dataset — what it said,
  how you caught it, what the truth was. If you honestly hit zero, say so and explain what verification you ran
  that would have caught one.
- One thing you did by hand because delegating it would have been slower or riskier.

### Part F — `README.md`

Setup, how to run, how to resume, where the outputs land. Then a **10-line maximum** summary of what you found —
the thing you would say out loud to an operations head who has 30 seconds. No preamble.

---

## 4. How this is scored

| Weight | What |
|---:|---|
| 30% | **Correctness of the numbers** — did the planted data defects corrupt your R1/R2 output |
| 25% | **Evidence discipline** — claims traced to real rows; no assertion standing on its own |
| 15% | **AI log quality** — honest, specific, shows you catch the model being wrong |
| 15% | **Engineering** — resumability, idempotency, config hygiene, readable code |
| 10% | **Spec & communication** — spec written first, ambiguity surfaced, 10-line summary lands |
| 5%  | **Performance work** — plan actually read and understood |

Instant disqualifiers: numbers in the report that your own code does not produce; an AI log that is obviously
retro-fitted; `except: pass`.

---

## 5. Follow-up round (45 min, live, if this clears)

Screen share. We hand you one new question against the same dataset that is not in this brief, and you work it in
front of us using your assistant exactly how you normally would. We are watching how you prompt, how you check, and
how fast you notice when the answer is wrong. Nothing to prepare.

---

## 6. Ground rules

- Any AI, any library, any search. Log it.
- If something in this brief contradicts the data, the data wins — write it down and proceed.
- Questions are welcome at any point and cost you nothing.
