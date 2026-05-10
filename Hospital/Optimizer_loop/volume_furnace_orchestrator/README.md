# Volume Furnace Orchestrator

## Purpose

Runtime cadence wrapper for the Stage A-H optimizer v2 pipeline. Runs the optimizer in a background daemon thread so the main pulse loop is never blocked.

## Ownership

- Cadence and context gating for optimizer execution
- Background async execution of Stage A-H pipeline
- Mode-aware activation telemetry
- Silver promotion of winning candidates via Pituitary

## Anti-Ownership

- Does not approve trades (Gatekeeper)
- Does not execute orders (Brain Stem / Treasury)
- Does not directly install Gold params in vault (Pituitary does that)

## Background Thread Architecture

On `__init__`, a daemon thread (`furnace-worker`) starts and blocks on a bounded `queue.Queue(maxsize=1)`. When a cadence tick fires:

- `handle_frame()` or `handle_pulse()` calls `_submit_pipeline()` and returns immediately
- `_submit_pipeline()` does `queue.put_nowait(job)` — if the worker is still running the previous pipeline, the job is silently dropped and `QUEUE_FULL` is recorded in telemetry
- The worker calls `engine.run_pipeline(**kwargs)`, stores the result, and calls `_promote_winner_to_silver()`

`shutdown()` sends a `None` sentinel to the queue and joins the worker with a 5-second timeout.

## Cadence Policy

| Mode | Policy |
|---|---|
| Live (external_cadence=False) | Every 3rd MINT |
| Live (external_cadence=True) | Every MINT |
| BACKTEST / simulation_mode | Every 4th scheduled activation |

## Entrypoints

**`handle_frame(pulse_type, frame, walk_seed)`**
Frame-truth path used by Soul. Reads execution_mode, regime_id, price, atr, stop_level from the BrainFrame. Applies `_coerce_context()` then `_validate_context()` then `_cadence_gate()` before submitting.

**`handle_pulse(pulse_type, regime_id, price, atr, stop_level, walk_seed)`**
Lightweight path for callers without a full BrainFrame. Same gate sequence.

## Context Coercion (`_coerce_context`)

Applied before validation — prevents warmup frames from suppressing execution:

| Missing value | Fallback |
|---|---|
| regime in {UNK, UNKNOWN, NONE, ""} | `"GLOBAL"` + `REGIME_FALLBACK` flag |
| atr ≤ 0 when price > 0 | `max(price × 0.001, 1e-6)` + `ATR_FALLBACK` flag |
| stop ≤ 0 when price > 0 and atr > 0 | `max(price − 1.5×atr, 1e-6)` + `STOP_FALLBACK` flag |

## Gate Sequence

1. `SHUTDOWN` — immediately if `shutdown_requested`
2. `CADENCE_GATE` — pulse_type must be `MINT`
3. `MODE_GATE` — execution_mode must be in `{DRY_RUN, PAPER, LIVE, BACKTEST}`
4. `SUPPORT_FLOOR` — `support_floor_ok` must be True (from walk_seed)
5. `MISSING_CONTEXT` — regime, price must be valid after coercion
6. `CADENCE_GATE` — cadence policy check (every 3rd MINT / every 4th activation)

## Silver Promotion (`_promote_winner_to_silver`)

After a successful pipeline run, if `summary["promoted"] == True` and `pituitary` is wired, loads the winner's `param_json` from `optimizer_candidate_library` and calls `pituitary.promote_silver(params, fitness, regime_id, source)`.

## State

`get_state()` returns:

```python
{
    "run_id", "execution_mode", "simulation_mode", "external_cadence",
    "pulse_count", "mint_count", "activation_count",
    "last_decision", "last_summary", "last_error",
    "worker_alive",   # bool — daemon thread health
    "queue_depth",    # 0 or 1
    "telemetry_tail"  # last 20 decision events
}
```

All shared state (`_last_summary`, `_telemetry`) is guarded by `threading.Lock`.

## Files

- `service.py` — `VolumeFurnaceOrchestrator` class
