# Cerebellum/Soul — Orchestrator

Drives the entire engine pulse-by-pulse; owns the BrainFrame lifecycle and lobe dispatch order.

## Role

Soul is invoked by the dashboard thread every 5-minute bar. It subscribes to OpticalTract for push-based data delivery and calls `_process_frame()` which runs all lobes in sequence. Soul also manages vault hot-reload, Amygdala persistence, Pineal melatonin, Pituitary growth hormone, and the ParamCrawler on every MINT.

## What It Does

- Initializes BrainFrame and mirrors Gold params to `frame.standards` on startup
- Calls `reset_pulse()` at the start of each pulse to clear ephemeral state
- Dispatches lobes in fixed order: Right_Hemisphere → Council → PonsExecutionCost → Left_Hemisphere → VolumeFurnace → (if tier1_signal) Gatekeeper → AllocationGland → Brain_Stem
- On MINT: always calls Brain_Stem (to execute any pending ACTION entry), then Amygdala, Pineal, vault check, Pituitary, Crawler
- Pre-computes Brain_Stem valuation before AllocationGland so `z_distance` is available for sizing
- Publishes serialized BrainFrame JSON to Redis key `mammon:brain_frame:{symbol}` after every pulse

## BrainFrame I/O

- **Reads:** entire frame (master coordinator)
- **Writes:** `frame.market.*` (symbol, mode, ts, ohlcv), `frame.standards` (Gold params), `frame.command.approved/ready_to_fire` (trade gate inhibit)

## Key Config

- `execution_mode` — DRY_RUN / PAPER / LIVE / BACKTEST
- `trading_enabled_provider` — callable returning bool (fornix/warmup gate)
- `synapse_persist_pulse_types` — which pulses Amygdala writes (default: MINT only)
- `deadlines` — per-lobe timing budgets (seconds)

## Files

- `orchestrator/service.py` — `Orchestrator`; full pulse loop
- `brain_frame/service.py` — `BrainFrame`; zero-copy shared state dataclass
- `utils/ward_manager.py` — cleans up stale ward state on boot
- `utils/timing.py` — `enforce_pulse_gate` helper
