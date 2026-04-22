# ⚖️ Medulla
### *The Policy and Ledger Authority*

**Role**: The final arbiter of trade execution and money state.

## Ownership
The Medulla evaluates system intent and manages mode-isolated accounting.

*   **Gatekeeper**: The policy authority. Implements the `decide()` contract, approving trades ONLY on `ACTION` pulses if composite `tier_score` and `council_score` meet Gold-configured thresholds (`gatekeeper_min_monte`, `gatekeeper_min_council`, `gatekeeper_threshold_cmp`).
*   **Inhibitor-First Logic**: Fails closed by default. Writes explicit inhibit reasons to `BrainFrame.command`.
*   **TreasuryGland**: The mode-scoped ledger authority. Tracks the complete lifecycle of trade intents (`ARMED`, `FILLED`, `CANCELED`, `REJECTED`, `TIMEOUT`). Exposes `mark_to_market(symbol, price)` — called every HOLD pulse by Brain Stem to keep `unrealized_pnl` and `market_price` live in `money_positions`. SELL fills are recorded via `fire_intent(..., "SELL")`, which closes the position and writes `realized_pnl`. P&L snapshots now use `gross = realized + unrealized` (slippage is a cost, not a gain).
*   **Mode Isolation**: Strictly separates accounting for `DRY_RUN`, `PAPER`, `LIVE`, and `BACKTEST`.

## Operational Clarification (2026-04-19)
Gate thresholds are optimizable parameters in the optimizer search space, but live decision authority remains here in Gatekeeper at runtime. Optimizer components do not bypass Medulla policy checks.

## Anti-Ownership (What it does NOT do)
*   Does **not** handle physical broker execution mechanics or API routing (Brain Stem).
*   Does **not** generate market ingestion or pulse material (Thalamus).

## Core Invariants
*   Must strictly isolate money state by execution mode (no cross-contamination).
*   Must audit every decision and intent transition for high-fidelity reconstruction.
