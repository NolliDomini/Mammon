# 🏹 Brain Stem
### *The Execution Edge*

**Role**: The final bridge to the physical broker.

## Ownership
The Brain Stem is responsible for translating system intent into market action.

*   **Trigger Protocol**: Converts approved `BrainFrame` intents into actionable broker orders.
*   **The Three-Gate Entry Protocol**: Enforces final safety checks (Risk Gate, Valuation Gate, Conviction Prior) before live execution.
*   **Deferred Execution**: Arms intents on the `ACTION` pulse and fires them on the subsequent `MINT` pulse.
*   **Safety Valves**: Automates exit logic (Stop Loss, Take Profit, Mean Reversion monitor).
*   **Adapter Routing**: Dynamically switches between mock/paper adapters and real Alpaca live execution based on system mode.

## Anti-Ownership (What it does NOT do)
*   Does **not** calculate alpha or structural signals.
*   Does **not** make final system policy/approval decisions (Medulla).
*   Does **not** handle internal accounting or PnL ledgers (Medulla).

## Core Invariants
*   Must implement the Mean-Dev Monitor to cancel trades that revert too quickly before execution.
*   Must never execute an order that was not explicitly armed during the preceding `ACTION` pulse.