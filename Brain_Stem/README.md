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
*   **Deferred Execution**: Arms intents on the `ACTION` pulse and fires them unconditionally on the subsequent `MINT` pulse. The `MEAN_DEV_CANCEL` gate between `ACTION` and `MINT` has been removed — the Council already embeds stddev context before `ACTION` fires, making the inter-pulse z-score check redundant.
*   **Safety Valves**: Automates exit logic (Stop Loss `mean - 1.5σ`, Take Profit `mean + 2.0σ`, Mean Reversion rollover). On every HOLD pulse, `mark_to_market()` is called to keep unrealized P&L live in the treasury.
*   **SELL Closes Position**: Exit triggers now call `treasury.fire_intent(..., "SELL")` to crystallize realized P&L and zero the position in the ledger.
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
*   Must never execute an order that was not explicitly armed during the preceding `ACTION` pulse.
*   Must call `mark_to_market()` on every HOLD pulse to keep unrealized P&L current.
*   Must call `treasury.fire_intent(..., "SELL")` on every exit to close the position in the ledger.
