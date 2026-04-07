# Amygdala Change Log (v3.0)

## [2026-02-28]
### Phase 1: Execution Friction
- **Piece 138**: Extended `synapse_mint` table schema in `MultiTransportLibrarian` and updated `Ecosystem_Synapse.schema.md` to include Phase 1 bid/ask, spread, valuation, and sizing fields.
- **Piece 139**: Updated `Amygdala` validation logic to require Phase 1 metrics (`bid_ask_bps`, `val_mean`, `exec_total_cost_bps`, `qty`) during the `MINT` pulse.
- **Piece 143**: Verified end-to-end synapse persistence of Phase 1 fields via integration tests in `Hippocampus/tests_v2/integration/test_soul_lifecycle_v4.py`.


