# Thalamus (Ingestion Lobe)

## Purpose
The Thalamus serves as the central data entry and resampling hub for the Mammon system. It transforms raw 1m market data from Alpaca into high-fidelity, resampled 5m "Triple-Pulse" events (SEED, ACTION, MINT) for the neural pipeline.

## Core Components

### 1. `Thalamus` (relay/service.py)
The primary ingestion service responsible for fetching and normalizing market data.
- `connect_stream()` / `stop_stream()`: Manages WebSocket connections for real-time 1m bar data.
- `pulse()`: Entry point for historical or batch ingestion.
- `drip_pulse()`: Entry point for real-time data, pushing raw bars to the `DuckPond` and aggregated bars to the `SmartGland`.
- `_normalize_bars()`: Enforces the `CANONICAL_COLS` schema (OHLCV + symbol + quote metrics + pulse_type).
- `get_snapshot()` / `get_latest_bar()`: Atomic Alpaca API calls for latest price/quote validation.

### 2. `SmartGland` (gland/service.py)
The vectorized resampler and pulse generator.
- `ingest()`: Processes 1m bars into 5m windows and yields SEED (+2.25m), ACTION (+4.5m), and MINT (boundary) pulses.
- `_agg_window()`: Aggregates OHLCV and quote data using Numba kernels.
- `_wrap_with_context()`: Concatenates the current pulse with a trailing history buffer (default: 50 bars).

### 3. `Math Kernels` (utils/math_kernels.py)
Numba-accelerated (`@njit`) utility functions for C-level performance.
- `aggregate_ohlcv_njit()`: Fast OHLCV window aggregation.
- `detect_pulse_indices_njit()`: Vectorized identification of intra-window pulse timestamps.

## Inputs & Outputs
- **Inputs**: Alpaca `Bar` objects, raw `pd.DataFrame`, or `market_tape` DuckDB rows.
- **Outputs**: `pd.DataFrame` containing canonical 5m pulses + history, delivered via `OpticalTract`.

## Dependencies
- `alpaca-py`: Data sourcing.
- `Cerebellum.Soul`: Unified timing invariants.
- `Corpus.Optical_Tract`: Synchronous broadcast bus.
- `Hippocampus.Archivist`: Multi-transport persistence.
- `Hippocampus.DuckPond`: Data lake persistence.