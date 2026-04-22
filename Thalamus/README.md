# 📡 Thalamus
### *The Ingestion Lobe*

**Role**: The entry point for the "Electricity" (Market Data).

## Ownership
Thalamus owns the fetch, normalization, and pulse-material generation phase of the Mammon pipeline. It acts as a "dumb" ingestion layer, devoid of trading logic or strategy math.

*   **Source Fetching**: Retrieves raw 1m bars from Alpaca or historical databases.
*   **Canonical Normalization**: Ensures all data conforms to strict OHLCV schema invariants.
*   **SmartGland**: Transforms raw 1-minute streams into the canonical Triple-Pulse rhythm (`SEED`, `ACTION`, `MINT`).
*   **Context Buffering**: Maintains the rolling 5-minute context window required by downstream components.

## Anti-Ownership (What it does NOT do)
*   Does **not** calculate indicators or environment confidence.
*   Does **not** dictate pulse cadence authority (Soul owns sequencing legality).
*   Does **not** authorize execution or interact with broker adapters.

## Connection Resilience
`get_latest_bar` retries up to 3 times with linear backoff (1.5s, 3s) on any network or SSL failure. On each retry the Alpaca client is rebuilt to flush exhausted connection pools. If all retries fail, the poll loop emits `THAL-E-CONN-001 / DATA_CONNECTION_DROP` to the MNER log, cancels any armed Brain Stem intent (stale data — window is lost), and skips the bar. The SmartGland resets cleanly on the next window boundary.

## Core Invariants
*   Must emit valid Triple-Pulse tuples or gracefully skip.
*   Must enforce causal sequence within every 5-minute window.
*   On connection drop, must cancel pending intents via MNER and reset to the next window rather than carrying stale state forward.