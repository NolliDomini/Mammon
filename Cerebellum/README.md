# Cerebellum — System Governor

The cadence authority and environmental intelligence center; contains Soul (orchestrator) and Council (environment scoring).

## Role

Cerebellum owns the pulse lifecycle. `Soul/orchestrator` drives every lobe in deterministic order each SEED/ACTION/MINT pulse. `Council` synthesizes ATR, ADX, VWAP, and spread into a single environmental confidence score and a 16-character regime ID.

## What It Does

- `Orchestrator` registers lobes, calls them in sequence, catches deadline violations, publishes BrainFrame snapshots to Redis
- `Council` runs four indicators (ATR ratio, ADX trend, spread score, VWAP distance) and blends them into `frame.environment.confidence`
- Council generates a `D_A_V_T` regime ID (4 binned dimensions) written to `frame.risk.regime_id`
- Hot-vault reload: on every MINT, Soul checks if the Gold param ID changed and pushes new params to all lobes
- `SpreadEngine` (sub-module) evaluates bid/ask friction each SEED and ACTION pulse

## Files

- `Soul/orchestrator/service.py` — `Orchestrator`; pulse loop, lobe registry, vault reload
- `Soul/brain_frame/service.py` — `BrainFrame`; zero-copy shared state
- `Soul/utils/` — timing helpers, ward manager
- `council/service.py` — `Council`; environmental indicator synthesis
- `council/spread_engine/service.py` — `SpreadEngine`; bid/ask spread evaluation
