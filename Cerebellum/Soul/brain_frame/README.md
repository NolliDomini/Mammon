# BrainFrame Change Log (v3.0)

## [2026-02-28]
### Phase 1: Execution Friction
- **Piece 20**: Added `bid_ask_bps` to `EnvironmentSlot` to support real-time spread telemetry.
- **Piece 21**: Added `spread_score` to `EnvironmentSlot` for indicator-driven spread evaluation.
- **Piece 22**: Added `spread_regime` string field to `EnvironmentSlot` for mode-based telemetry.
- **Piece 23**: Added `spread_inputs` dictionary to `EnvironmentSlot` for granular indicator tracking.
- **Piece 24**: Created `ValuationSlot` dataclass to hold mean-reversion metrics (`mean`, `std_dev`, `bands`, `z_distance`).
- **Piece 25**: Registered `ValuationSlot` in `BrainFrame.__init__` for zero-copy reference passing.
- **Piece 26**: Created `ExecutionSlot` dataclass for pre-trade friction tracking (`slippage`, `fees`, `total_cost`).
- **Piece 27**: Registered `ExecutionSlot` in `BrainFrame.__init__` for zero-copy reference passing.
- **Piece 28**: Added `qty` to `CommandSlot` to support precise order sizing.
- **Piece 29**: Added `notional` to `CommandSlot` for cash-equivalent trade tracking.
- **Piece 30**: Added `size_reason` to `CommandSlot` for auditability of allocation logic.
- **Piece 31**: Added `risk_used` to `CommandSlot` to track capital utilization per trade.
- **Piece 32**: Added `cost_adjusted_conviction` to `CommandSlot` for friction-aware execution thresholding.
- **Piece 33**: Updated `reset_pulse()` to atomically clear `ValuationSlot`, `ExecutionSlot`, and Phase 1 allocation telemetry at the start of each pulse.
- **Piece 34**: Verified fail-closed defaults (`qty=0.0`, `ready_to_fire=False`) in `CommandSlot` to prevent accidental execution without allocation logic.
- **Piece 36**: Verified subscriber contract tolerance for expanded slots via `Hippocampus/tests_v2/contracts/test_brain_frame_v4_compatibility.py`.
- **Piece 37**: Verified `ValuationSlot` safe default integrity in unit tests.
- **Piece 38**: Verified `ExecutionSlot` safe default integrity in unit tests.
- **Piece 39**: Verified `reset_pulse()` field clearance across all slots in unit tests.
- **Piece 40**: Updated and verified `to_synapse_dict()` to include Phase 1 flattened fields for DuckDB/Synapse persistence.
- **Piece 41**: Updated and verified `check_in()` and `check_out()` for full sub-millisecond Redis state persistence of all Phase 1 slots.
- **Piece 42**: Verified `OpticalTract.spray()` compatibility with extended Phase 1 DataFrames in unit tests.
- **Piece 137**: Extended `to_synapse_dict()` to include all Phase 1 friction and sizing fields for flattened Synapse persistence.


