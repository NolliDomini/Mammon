# Optimizer Loop Rebuild

Status: Stage A-H v2 pipeline is active.

Legacy optimizer scripts were mothballed on:
- 2026-02-19
- Archive: `C:\Users\Mammon\Desktop\Wick Works\Mammon_Mothball\Optimizer\2026-02-19_214016`

Active runtime entrypoint:
- `volume_furnace_orchestrator.py` exposes `VolumeFurnaceOrchestrator`
- Soul contract path calls `handle_frame(pulse_type, frame, walk_seed)` to consume BrainFrame truth directly.
- Executes v2 cadence on MINT
 - every 3rd MINT runs Stage A-H pipeline
 - `execution_mode=BACKTEST` (or `simulation_mode=True`) enables 25% cadence mode
 - explicit skip reasons: `CADENCE_GATE`, `MODE_GATE`, `MISSING_CONTEXT`, `SUPPORT_FLOOR`, `SHUTDOWN`

Core implementation:
- `optimizer_v2.py` runs Stage A-H redesign:
 - edge LHS scan
 - semi-middle band extraction
 - candidate library fill + diversity floor
 - walk context simulation + regime support floor
 - walk-conditioned Monte score vector persistence
 - focused refine + entropy collapse burst
 - Bayesian ranking + diagnostics
 - promotion gate with reason-coded fail-safe decisions

Operational boundary (2026-04-19):
- Optimizer/Furnace runs candidate scoring and promotion decisions.
- It does **not** directly execute trades.
- It does **not** directly bypass Medulla/Brain Stem gates.
- Gold parameter changes affect live trading only after vault write/coronation and Soul hot-reload.
