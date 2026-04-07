# Fornix

## Purpose
Fornix is Mammon's historical replay conduit. It carries stored market memory from Hippocampus into the live-equivalent pulse pipeline for backtest-grade synthesis and optimizer training.

Primary file:
- `Hippocampus/fornix.py`

## Hard Boundary
Fornix is a transport/replay engine, not a separate strategy engine.

It must:
- replay historical bars through the same pulse rhythm used by runtime
- route bars through SmartGland and Soul orchestration
- mint historical synapse tickets for downstream optimizer use

It must not:
- bypass core orchestration contracts
- create alternate decision policy rules outside canonical runtime components

## Runtime Flow
1. Read chunked bars from DuckPond (`market_tape`) by symbol/time.
2. Feed bars into `SmartGland.ingest(...)` to get SEED/ACTION/MINT tuples.
3. Route each emitted pulse through `Cerebellum.Soul.Orchestrator` (canonical lobe sequence).
4. Keep MINT persistence active through Amygdala/SynapseScribe and stage replay snapshots in DuckDB `history_synapse`.
5. Keep optimizer cadence under Soul-orchestrated runtime contract (no Fornix-local optimizer fork).
6. Finalize run and hand off staging cleanup to Pineal.

## Replay Fidelity Controls
Common controls include:
- symbol subset selection
- runtime hour caps
- resume/checkpoint toggle
- reduced Monte fidelity for test pulses vs full-fidelity replay

## State and Persistence
Fornix writes/uses:
- `history_synapse` staging in DuckDB
- checkpoint records for resumable replay
- minted telemetry through normal module writers

Final staging cleanup authority belongs to Pineal after consumption.

## Invariants
- Replay must preserve causal order and pulse semantics.
- Historical path should reuse runtime contracts, not fork them.
- MINT-only historical synapse writes are expected unless explicitly expanded.

## Related Docs
- `Hippocampus/README.md`
- `Hippocampus/PINEAL_README.md`
- `Hippocampus/Plans/MASTER_MAMMON_CHECKLIST.md`
