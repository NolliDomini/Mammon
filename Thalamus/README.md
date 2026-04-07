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

## Core Invariants
*   Must emit valid Triple-Pulse tuples or gracefully skip.
*   Must enforce causal sequence within every 5-minute window.