# Amygdala

## Purpose
Amygdala is Mammon's synapse-ticket mint authority for runtime state capture.

It owns:
- flattening the current `BrainFrame` snapshot into a synapse ticket
- deciding persistence cadence for ticket minting
- handing ticket persistence to `SynapseScribe`

It does not own:
- signal generation
- execution authorization
- broker execution
- data-lake staging/wipe policy

Primary runtime file:
- `Hippocampus/amygdala.py`

## Runtime Contract
Primary method:
- `mint_synapse_ticket(pulse_type, frame)`

Behavior:
- ignores non-`MINT` pulses
- on `MINT`, calls `frame.to_synapse_dict()`
- validates required schema keys before write
- composes deterministic `machine_code` (`mode|pulse|symbol|regime|decision|ts`)
- routes writes by mode (`BACKTEST` -> dedicated synapse DB, runtime modes -> primary synapse DB)
- writes ticket via `Hippocampus/Archivist/synapse_scribe.py`
- updates local telemetry state:
  - `mint_count`
  - `last_mint_ts`
  - `last_machine_code`
  - `last_write_status` / error fields

## Persistence Target
SQLite DB:
- `Hippocampus/Archivist/Ecosystem_Synapse.db`
- `Hippocampus/Archivist/Ecosystem_Synapse_Backtest.db` (BACKTEST mode)

Table:
- `synapse_mint`

Primary key:
- `(ts, symbol, pulse_type)`

Payload shape:
- market OHLCV + structure + risk + environment + command fields
- `machine_code` TEXT for one-hop lookup identity
- canonical field set documented in:
  - `Hippocampus/Context/00_READ_FIRST_CANON/SCHEMA_KEYS/Ecosystem_Synapse.schema.md`

## Operational Invariants
- Only `MINT` tickets are persisted by Amygdala.
- Ticket writes are idempotent by `(ts, symbol, pulse_type)` key.
- Serialization must sanitize unsupported values (NaN/inf/datetime objects) before storage.
- `machine_code` generation is deterministic for identical frame inputs.
- Amygdala failure must not crash the core pulse loop.

## Boundary With Other Components
- Orchestrator invokes Amygdala in the pulse cycle.
- `SynapseScribe` owns schema/bootstrap and insert path.
- Pituitary/Refinery consume `synapse_mint` for parameter learning workflows.
- Pineal cleanup rules may purge non-MINT rows elsewhere; Amygdala itself emits MINT-only.

## Testing Expectations
Minimum coverage:
- non-MINT pulses do not write
- MINT pulses write exactly one ticket
- ticket includes required schema keys
- duplicate key behavior is stable (replace/upsert semantics)
