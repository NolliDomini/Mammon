# 🏹 Brain Stem
### *The Execution Edge*

**Role**: The final bridge to the physical broker.

## Ownership
The Brain Stem is responsible for translating system intent into market action.

*   **Trigger Protocol**: Converts approved `BrainFrame` intents into actionable broker orders.
*   **The Three-Gate Entry Protocol**: Enforces final safety checks before execution:
    * Risk gate: `risk >= gatekeeper_min_monte`
    * Valuation cap: entry z-score must be `<= brain_stem_entry_max_z`
    * Conviction gate: prior confidence must pass baseline threshold
*   **Deferred Execution**: Arms intents on the `ACTION` pulse and fires them on the subsequent `MINT` pulse.
*   **Safety Valves**: Automates exit logic (Stop Loss, Take Profit, Mean Reversion monitor).
*   **Adapter Routing**: Dynamically switches between mock/paper adapters and real Alpaca live execution based on system mode.

## Current Runtime Defaults (2026-04-19)
The active scalper profile in Gold (`scalp_v1_20260419`) is tuned for faster decision cadence:
*   `active_gear = 3`
*   `gatekeeper_min_monte = 0.30`
*   `gatekeeper_min_council = 0.44`
*   `brain_stem_entry_max_z = 0.8`

Guardrails are still enforced at Brain Stem/Treasury level:
*   `max_notional_per_order`
*   `max_open_positions`
*   `max_daily_realized_loss`

## Anti-Ownership (What it does NOT do)
*   Does **not** calculate alpha or structural signals.
*   Does **not** make final system policy/approval decisions (Medulla).
*   Does **not** handle internal accounting or PnL ledgers (Medulla).

## Core Invariants
*   Must implement the Mean-Dev Monitor to cancel trades that revert too quickly before execution.
*   Must never execute an order that was not explicitly armed during the preceding `ACTION` pulse.
