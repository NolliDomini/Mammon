# Corpus (Synthesis & Transport)

## Purpose
The Corpus serves as the system's neural bridge and broadcast hub. It synthesizes signals from multiple hemispheres into a final Tier Score and orchestrates the high-speed fan-out of market pulses to all subscribed neural lobes.

## Components

### 1. `Callosum` (callosum/service.py)
The deterministic signal synthesizer.
- `score_tier()`: Blends `monte_score` (Risk) and `tier1_signal` (Structure) using weighted averages to produce the final `tier_score`.
- **Zero-Copy Contract**: Writes the synthesized score directly to the `BrainFrame.risk` slot.

### 2. `OpticalTract` (Optical_Tract/spray.py)
The synchronous pulse broadcaster.
- `subscribe()` / `unsubscribe()`: Manages the registry of lobes and engines listening for market data.
- `spray()`: Executes the high-velocity, synchronous delivery of `pd.DataFrame` pulses to all registered subscribers with a 50ms soft latency budget and persistent failure auditing in TimescaleDB.

## Inputs & Outputs
- **Inputs**: `pd.DataFrame` (Market Pulse) from `Thalamus`; `BrainFrame` for synthesis.
- **Outputs**: Synchronous data delivery to all registered subscribers; updated `BrainFrame.risk.tier_score`.

## Dependencies
- `Cerebellum.Soul`: BrainFrame contract and timing gate.
- `Hippocampus.Archivist`: Persistent audit logging for broadcast failures.