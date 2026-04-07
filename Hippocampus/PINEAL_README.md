# Pineal

## Purpose
Pineal is Mammon's memory hygiene and staging finalization authority.

It owns:
- retention and pruning policy for short-lived memory artifacts
- strict non-MINT purge behavior in selected SQLite mint tables
- Fornix staging finalization flow for DuckDB `history_synapse`

It does not own:
- signal generation
- optimization strategy selection
- execution authorization or broker order routing

Primary runtime file:
- `Hippocampus/pineal.py`

## Core Responsibilities

### 1) Melatonin Cleanup Cycle
`secrete_melatonin(...)` performs two phases:
1. Purge non-MINT rows from targeted mint tables.
2. Apply time-based retention pruning on configured tables.

Primary DB targets:
- `Hippocampus/Archivist/Ecosystem_Memory.db`
- `Hippocampus/Archivist/Ecosystem_Synapse.db`
- `Hippocampus/Archivist/Ecosystem_Optimizer.db`
- `Hospital/Memory_care/control_logs.db`

Retention is configured through an internal map (`retention_map`) in hours.

### 2) Fornix Staging Finalization Authority
`finalize_fornix_staging(pond, consumed_by_diamond, run_id)`:
- archives staged synapse rows first (`archive_history_synapse`)
- clears staging (`clear_history_synapse`) only when `consumed_by_diamond=True`
- preserves staged data when Diamond did not consume the run

This is the authoritative gate for post-Fornix wipe behavior.

## Data Contract
DuckDB staging tables involved:
- `history_synapse` (staging)
- `brainframe_mint_archive` (long-lived archive)
- `fornix_checkpoint` (resume state)

Expected finalization sequence:
1. Run Fornix replay and write staged `history_synapse`.
2. Run Diamond consumption step.
3. Call Pineal finalization:
   - always archive
   - wipe only on confirmed consumption

## Operational Invariants
- Pineal must never clear staged synapse before archival attempt.
- Wipe decisions are consumption-gated, not time-gated.
- Cleanup failures must degrade safely (log errors, avoid crashing full runtime loop).
- Non-MINT pruning must not mutate schema or block execution pipeline.

## Known Constraints
- `secrete_melatonin(pulse_type=...)` currently accepts `pulse_type` but does not branch on it internally.
- Retention map may include tables not present in every environment; implementation skips missing tables safely.
- Some cleanup SQL paths are SQLite-specific and are not applied to DuckDB staging (DuckDB staging is finalized via `DuckPond` methods).

## Tests
Contract test:
- `Hippocampus/tests_v2/contracts/test_pineal_fornix_finalize.py`

What it verifies:
- archive is always called
- wipe occurs only when `consumed_by_diamond=True`

## Boundary With Other Glands
- Fornix produces staging data and invokes Pineal finalize path.
- Diamond determines whether staging was consumed.
- Pineal decides whether staging is wiped after that signal.
- Pituitary consumes parameter outputs but does not own staging wipe authority.
