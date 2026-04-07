# SpreadEngine Change Log (v3.0)

## [2026-02-28]
### Phase 1: Execution Friction
- **Piece 43**: Created `Cerebellum/council/spread_engine/__init__.py` to initialize the spread indicator module.
- **Piece 44**: Created `service.py` with the `SpreadEngine` class implementing the standard `evaluate(pulse_type, frame)` contract.
- **Piece 45**: Implemented a pulse gate to restrict evaluation to `SEED` and `ACTION` pulses, ensuring zero overhead on `MINT`.
- **Piece 46**: Implemented `bid`/`ask` extraction logic from `frame.market.ohlcv` passthrough columns with fallback to `close`.
- **Piece 47**: Added `_raw_spread_bps` helper for high-precision basis point spread calculation.
- **Piece 48**: Implemented strict validation for bid/ask consistency with MNER `COUNCIL-E-P48-301` for data integrity failures.
- **Piece 49**: Implemented ATR-based fallback calculation (`atr_bps * spread_atr_ratio`) for scenarios with missing or invalid real-time quotes.
- **Piece 50**: Implemented `_calculate_score` using a distance-from-ATR model to normalize liquidity friction into a 0.0-1.0 confidence score.
- **Piece 51**: Implemented `_calculate_regime` to categorize liquidity conditions (TIGHT, NORMAL, WIDE, STRESSED) based on Gold thresholds.
- **Piece 52**: Established "Diagnostic-Only" policy for the spread engine; it provides rich telemetry but does not inhibit pulse authorization.
- **Piece 53**: Integrated `evaluate()` outputs directly into `BrainFrame.environment` slots for downstream lobe consumption.
- **Piece 125**: Implemented neutral-score guard (`spread_score = 0.0`) for all runtime and logic failure paths.
- **Piece 125**: Verified neutral-score guard (`spread_score = 0.0`) for runtime failure paths, ensuring robust Council synthesis.
- **Piece 56**: Explicitly mapped `COUNCIL-E-SPR-701` for invalid bid/ask quote detection.
- **Piece 57**: Explicitly mapped `COUNCIL-E-SPR-702` for missing input columns, triggering automatic ATR fallback.
- **Piece 58**: Implemented `COUNCIL-E-SPR-703` for spread-to-confidence normalization failures.
- **Piece 59**: Implemented top-level MNER `COUNCIL-E-SPR-704` for unexpected `evaluate()` runtime exceptions.
- **Piece 60**: Verified happy-path spread logic (bps, score, regime) via unit tests in `Hippocampus/tests_v2/contracts/test_spread_engine_contract.py`.
- **Piece 61**: Verified invalid quote detection (`bid <= 0`, `ask < bid`) and MNER `COUNCIL-E-SPR-701` triggering ATR fallback in unit tests.
- **Piece 62**: Verified missing column handling and MNER `COUNCIL-E-SPR-702` triggering ATR fallback in unit tests.
- **Piece 63**: Verified regime boundary transitions (TIGHT, NORMAL, WIDE, STRESSED) in unit tests.
- **Piece 66**: Verified pulse gating logic correctly skips `MINT` pulses in unit tests.


