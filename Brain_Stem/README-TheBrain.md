# Brain Stem (Execution Edge)

## Purpose
The Brain Stem serves as the system's final interface with the market. It enforces multi-gate safety protocols, calculates pre-trade execution costs, and orchestrates the physical order lifecycle (Arm/Fire/Cancel/Exit) across mock and live Alpaca adapters.

## Components

### 1. `Trigger` (trigger/service.py)
The V3.3 Gated Execution Engine.
- `load_and_hunt()`: The primary entry point. Orchestrates the **ACTION (Arm)** and **MINT (Fire)** sequence.
- **Risk Gate**: Enforces a "Small Monte" safety check (`risk_score > 0.5`).
- **Valuation Gate**: Calculates dynamic StdDev bands and Fair Value (`Price < Mean`) using a 10k-path simulation.
- **Mean-Dev Monitor**: Automated trade cancellation on MINT if price reverts too quickly before execution.
- **Exit Logic**: Automates position closing via `SAFETY_VALVE_STOP`, `TAKE`, and `MEAN_REV` (Price rollover).

### 2. `PonsExecutionCost` (pons_execution_cost/service.py)
The pre-trade friction engine.
- `estimate()`: Calculates total expected cost (`total_cost_bps`) by blending Half-Spread, Market Impact, and Volatility-adjusted slippage + broker fees.
- **Conservative Guard**: Fails closed by applying `max_cost_cap_bps` if inputs are missing or malformed.

## Inputs & Outputs
- **Inputs**: `BrainFrame` containing policy decisions and market pulses; `Alpaca` API credentials.
- **Outputs**: Physical order submissions to Alpaca; direct updates to `BrainFrame.valuation` and `BrainFrame.execution`.

## Dependencies
- `Cerebellum.Soul`: `BrainFrame` and timing gate.
- `Medulla.treasury`: Financial ledger persistence and position state.
- `alpaca-py`: Broker API interface.