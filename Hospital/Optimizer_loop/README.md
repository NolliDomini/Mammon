# Optimizer Loop

Stage A-H v2 pipeline. Active.

## Runtime

The `VolumeFurnaceOrchestrator` wraps `OptimizerV2Engine` and fires it from a **background daemon thread** — the pipeline never blocks the main pulse loop. A bounded queue (maxsize=1) drops jobs silently when the worker is still running.

Soul contract: `handle_frame(pulse_type, frame, walk_seed)` — called each pulse; pipeline only activates on eligible MINTs.

## Cadence

| Mode | Cadence |
|---|---|
| Live (`external_cadence=False`) | Every 3rd MINT |
| Live (`external_cadence=True`) | Every MINT |
| BACKTEST / simulation_mode | Every 4th scheduled activation |

Skip reasons recorded in telemetry: `CADENCE_GATE`, `MODE_GATE`, `MISSING_CONTEXT`, `SUPPORT_FLOOR`, `SHUTDOWN`, `QUEUE_FULL`.

## Pipeline Stages

| Stage | Name |
|---|---|
| A | Edge LHS scan |
| B | Semi-middle band extraction |
| C | Candidate library fill + diversity floor |
| D | Walk context simulation + regime support floor |
| E | Vectorized Monte score |
| F | Focused LHS refine |
| G | Bayesian exploit cadence |
| H | Promotion gate (score / drawdown / stability / slippage / support / diversity) |

## Operational Boundary

- Optimizer scores candidates and decides promotion — it does not execute trades
- It does not bypass Medulla or Brain Stem gates
- Gold parameter changes take effect only after vault write/coronation and Soul hot-reload (`_check_vault_mutation()` on each MINT)

## Search Space

24-D. See `bounds/README.md` for full parameter table.
