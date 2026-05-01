# Corpus/Optical_Tract — OpticalTract

Synchronous pulse fan-out bus: broadcasts each OHLCV DataFrame to all registered lobes.

## Role

Thalamus calls `spray(df)` after building a pulse DataFrame. OpticalTract iterates its subscriber list and calls `on_data_received(df)` on each. The Orchestrator subscribes to OpticalTract so data flows Thalamus → OpticalTract → Orchestrator → lobes without double-ingestion.

## What It Does

- `subscribe(lobe)` registers any object with `on_data_received`; deduplicates re-subscriptions
- `spray(df)` delivers to all subscribers synchronously; per-subscriber exceptions are caught and counted without blocking other deliveries
- Tracks delivery timing per-subscriber via `delivery_stats` numpy array
- Publishes delivery summary (count, failures, total time) to Redis via Librarian

## BrainFrame I/O

- **Reads:** raw pulse DataFrame (before it enters BrainFrame)
- **Writes:** nothing directly — triggers Orchestrator which owns BrainFrame

## Files

- `spray.py` — `OpticalTract`; subscribe/unsubscribe/spray
- `adapters.py` — format adapters for DataFrame normalization
