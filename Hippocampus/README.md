# 🏛️ Hippocampus
### *The Persistence and Memory Authority*

**Role**: The asynchronous nervous system for system storage and historical recall.

## Ownership
The Hippocampus is the sole authority for database interactions and system logging.

*   **Telepathy**: Async persistence daemon. Manages non-blocking SQL write queues to handle lock contention.
*   **Amygdala (State-Scribe)**: Flattens the `BrainFrame` into persistent "Synapse Tickets" during the `MINT` pulse, generating deterministic 16-character `machine_code` identifiers.
*   **DuckPond**: The DuckDB-powered Data Lake manager for raw market tapes and historical snapshots.
*   **Fornix**: The Memory Replay Engine. Feeds historical DuckDB tapes back through the live pipeline (Soul) for high-fidelity backtesting.
*   **Pineal**: Memory hygiene, schema validation, and lifecycle pruning.

## Anti-Ownership (What it does NOT do)
*   Does **not** make strategic trading decisions.
*   Does **not** directly execute market orders.
*   Does **not** mutate incoming historical data during replay (Forxix simply acts as a conduit).

## Core Invariants
*   **MINT-Only Persistence**: `SEED` and `ACTION` pulses remain ephemeral; only finalized `MINT` state is committed to the Synapse.
*   **Siloed Persistence**: Writes are strictly routed to `Production` or `Backtest` databases based on execution mode.