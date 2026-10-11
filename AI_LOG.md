# AI Usage Log

## Assistants used

- ChatGPT: assisted with pipeline implementation, MySQL reporting,
  debugging, performance analysis, and documentation.
- MySQL Workbench and PowerShell: used to execute SQL, run scripts,
  inspect outputs, and verify results.

## Three most consequential prompts

The exact wording of the earlier pipeline-generation prompts is not
preserved in the available conversation record. They are not reproduced
here as verbatim quotations because reconstructing them would be misleading.

1. Verbatim prompt available from the current record:
   "ab kya karu jisse jald se jald yah assignment complete ho"

2. Earlier prompt: pipeline generation and checkpoint/resume implementation.
   Exact wording unavailable; not quoted as verbatim.

3. Earlier prompt: generation of the R1 communication, R2 DTR energy
   balance, and R3 exceptions reports.
   Exact wording unavailable; not quoted as verbatim.

## Verification and potential AI failure modes

No two specific cases of a confident but incorrect AI answer have been
conclusively established from the available evidence. The following
verification checks were performed to reduce the risk of plausible errors:

1. Duplicate HES readings:
   The report identified repeated reading groups. Examples include
   serial 700000160 with 16 repeated rows and serial 700000222 with
   31 repeated rows. The report states that duplicate readings are
   deduplicated for metrics while raw database rows are retained.

2. Timestamp-shift suspicion:
   The report identified readings whose import_wh value also appears
   at a timestamp exactly 330 minutes earlier. This is classified as a
   possible IST/UTC shift, not a confirmed root cause. Source timestamps
   require further verification.

3. Cumulative register handling:
   HES import_wh is a cumulative register, not interval consumption.
   The reporting logic calculates chronological deltas and handles
   resets and rollover explicitly. R2 values and exclusions should be
   checked against the source rows.

## Manual verification

I ran the full-dataset pipeline, checked the generated report counts,
inspected actual exception evidence, and executed MySQL EXPLAIN ANALYZE
before and after creating a composite index. The observed query plan
changed from table scan plus sort to a covering index scan.

## Known limitation

The original exact prompts and a verified pair of incorrect AI answers
must be recovered from the original chat history if available. This log
does not claim those assignment requirements are fully satisfied.
