# Medulla (Policy & Treasury)

## Purpose
The Medulla serves as the system's final decision and financial authority. It enforces trade policies, calculates precise position sizing based on mean-reversion conviction, and maintains mode-isolated persistent ledgers for order lifecycle auditing and PnL tracking.

## Components

### 1. `Gatekeeper` (gatekeeper/service.py)
The final policy authority.
- `decide()`: Evaluates `tier_score` (Risk) and `council_score` (Environment) against mode-specific thresholds to approve or inhibit trade intents.
- **Fail-Closed Policy**: Inhibits trades by default if thresholds are not met or inputs are invalid.

### 2. `AllocationGland` (allocation_gland/service.py)
The mean-reversion sizing engine.
- `allocate()`: Calculates order quantity proportional to `z_distance` (price deviation from mean) while penalizing for expected execution cost (`total_cost_bps`).
- **Hard Caps**: Enforces `max_notional` and `max_qty` limits to prevent risk breaches.
- **Zero-Copy Performance**: Writes allocation outputs directly to the `BrainFrame.command` slot.

### 3. `TreasuryGland` (treasury/gland.py)
The persistent money-state manager.
- **Persistent Ledgers**: Maintains `money_orders`, `money_fills`, and `money_positions` in TimescaleDB with strict mode isolation (DRY_RUN, PAPER, LIVE, BACKTEST).
- `record_intent()`: Persists trade intents upon ACTION pulse approval.
- `fire_intent()`: Records trade execution, calculates realized/unrealized PnL, and updates position ledgers.
- `get_status()`: Aggregates real-time KPIs (orders, fills, PnL) for the dashboard.

## Inputs & Outputs
- **Inputs**: `BrainFrame` containing synthesized scores and valuation metrics.
- **Outputs**: Direct updates to `BrainFrame.command` (`approved`, `qty`, `notional`, `reason`); persistent entries in TimescaleDB financial ledgers.

## Dependencies
- `Cerebellum.Soul`: BrainFrame contract and timing gate.
- `Hippocampus.Archivist`: Multi-transport persistence (TimescaleDB).
- `Brain_Stem.trigger`: Consumer of Gatekeeper decisions.