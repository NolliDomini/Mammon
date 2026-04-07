# ⚖️ Medulla
### *The Policy and Ledger Authority*

**Role**: The final arbiter of trade execution and money state.

## Ownership
The Medulla evaluates system intent and manages mode-isolated accounting.

*   **Gatekeeper**: The policy authority. Implements the `decide()` contract, approving trades ONLY on `ACTION` pulses if composite `tier_score` and `council_score` exceed thresholds.
*   **Inhibitor-First Logic**: Fails closed by default. Writes explicit inhibit reasons to `BrainFrame.command`.
*   **TreasuryGland**: The mode-scoped ledger authority. Tracks the complete lifecycle of trade intents (`ARMED`, `FILLED`, `CANCELED`, `REJECTED`, `TIMEOUT`).
*   **Mode Isolation**: Strictly separates accounting for `DRY_RUN`, `PAPER`, `LIVE`, and `BACKTEST`.

## Anti-Ownership (What it does NOT do)
*   Does **not** handle physical broker execution mechanics or API routing (Brain Stem).
*   Does **not** generate market ingestion or pulse material (Thalamus).

## Core Invariants
*   Must strictly isolate money state by execution mode (no cross-contamination).
*   Must audit every decision and intent transition for high-fidelity reconstruction.