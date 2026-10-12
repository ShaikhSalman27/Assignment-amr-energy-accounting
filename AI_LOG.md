# AI Usage Log

## Assistants and tools used

- ChatGPT: assistance with Python pipeline implementation, MySQL report
  logic, checkpoint/resume debugging, performance analysis, and documentation.
- MySQL Workbench: SQL execution, duplicate detection, timestamp comparison,
  and EXPLAIN ANALYZE before and after indexing.
- PowerShell: pipeline execution, CSV inspection, file management, and Git.

## Prompts

The following are prompts whose wording is available in the conversation.
Earlier implementation prompts were not fully preserved in this log, so
they are not reconstructed and presented as verbatim text.

1. "ab kya karu jisse jald se jald yah assignment complete ho"
2. "ab next kya karu or is assignment ka aaj last day he please jald se jald complete karne me help karo"
3. "ab kya update karu"

These prompts relate to prioritizing completion and documentation. They are
not claimed to be the three original technical prompts that did the most work.
The exact wording of earlier technical prompts should be recovered from
the original chat history if available.

## Verification performed

### 1. Duplicate HES readings

MySQL query grouped readings by device_serial, data_timestamp, and import_wh
and returned groups with COUNT(*) > 1. Actual examples included serial
900001837 with duplicate_count = 2 at five timestamps on September 24–26.
The R3 report also contains 1,960 EXACT_DUPLICATE_HES_READINGS exception
records. The reporting pipeline states that duplicate readings are
deduplicated for metrics while raw database rows remain in MySQL.

### 2. Possible timestamp shift

A MySQL self-join compared readings with the same device_serial and import_wh
at timestamps exactly 330 minutes apart. Actual matching examples were found
for serial 700000160. The R3 report contains 8,296
POSSIBLE_IST_UTC_SHIFT_PLUS_330_MIN exceptions. This is evidence of a
timestamp pattern, not proof that the source timezone is wrong.

### 3. Performance plan

Before the index, EXPLAIN ANALYZE showed a table scan and a Sort node, with
approximately 12.254 seconds to complete. After creating
idx_hes_report_order, the plan used a covering index scan and took
approximately 5.102 seconds. This was a query-level benchmark, not a
measurement of total report-pipeline speedup.

## Manual work

I manually ran SQL in MySQL Workbench, inspected actual returned rows,
interrupted the pipeline with Ctrl+C after chunk 352, restarted it, and
verified that it resumed from chunk 353 and completed chunk 571.

## AI-error verification requirement — incomplete

I have not yet established two specific cases where an AI assistant gave a
confident but incorrect answer on this dataset. I will not invent such cases.
The checks above are verification examples, not claims that an AI answer was
proved wrong. This requirement remains incomplete unless genuine examples
can be recovered from the original interaction history.

## Limitations

The original technical prompts and two verified AI-error examples are not
fully available in this log. This file distinguishes confirmed test evidence
from unresolved requirements rather than claiming full compliance.
