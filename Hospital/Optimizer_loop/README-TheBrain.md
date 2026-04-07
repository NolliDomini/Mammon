# Optimizer Loop

Status: Active runtime module (updated 2026-03-01)

Purpose:
- Runs the staged optimizer/furnace pipeline and promotion logic.

Primary entrypoints:
- `Hospital/Optimizer_loop/volume_furnace_orchestrator/service.py`
- `Hospital/Optimizer_loop/optimizer_v2/service.py`

Current contract:
- Stage D walk context and Stage E Monte scoring share the same mutation stream contract.


