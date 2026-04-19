# Soul

## Purpose
Soul is Mammon's orchestration authority.

It owns:
- pulse-cycle sequencing across lobes
- pulse cadence authority (`SEED`/`ACTION`/`MINT`) via incoming pulse materials
- shared BrainFrame lifecycle per pulse
- timing/deadline telemetry for lobe execution
- runtime trade-gate wiring into execution path
- hormonal parameter injection at lobe registration

It does not own:
- raw market ingestion source authority (Thalamus)
- final policy thresholds (Medulla Gatekeeper)
- broker order adapter logic (Brain Stem)

Primary runtime file:
- `Cerebellum/Soul/orchestrator.py`

## Runtime Contract
Primary class:
- `Orchestrator`

Core entrypoints:
- `register_lobe(name, instance)`
- `pulse(symbols, is_crypto=True, data_override=None)`
- `on_data_received(data)` (Optical Tract subscriber hook)

Core cycle in `_process_frame(...)`:
1. reset/populate shared `BrainFrame`
2. run right hemisphere structure step
3. run council environment step
4. run left hemisphere readiness/seed path
5. run optimizer cadence hook (Volume Furnace)
6. run corpus + gatekeeper + brain stem when signal conditions are met
7. mint runtime synapse ticket through Amygdala
8. run Pineal/Pituitary maintenance hooks

## Pulse and Trade Gate Behavior
- Pulse type is read from incoming data (`pulse_type` column).
- Soul assigns and enforces cycle cadence; Thalamus does not author policy/legality for pulses.
- Runtime trade gate is provided by `config["trading_enabled_provider"]`.
- Evaluation of trade-gate/mode legality happens at the Soul boundary (start of `_process_frame`).
- If trade gate is false, Soul inhibits fire even when upstream scores are green.
- **Timing Guard (Piece 16):** Soul enforces a 30-second wall-clock ACTION->MINT expiry. Late MINTs trigger a `TIMING_CANCEL` inhibiting execution.
- Brain Stem MINT finalization path is still executed for deferred ACTION lifecycle closure or cancellation.

## Parameter Governance
- Soul loads Gold from `Hippocampus/hormonal_vault.json` at init.
- **Hot-Reload (Piece 14):** Soul checks for vault mutations on every MINT pulse and hot-reloads all lobe parameters if a new standard is coronated.
- On `register_lobe` (and hot-reload), Gold params are injected into lobe configs.
- Left hemisphere receives explicit noise/lane-weight injections for runtime consistency.
- Gatekeeper and Brain Stem consume those injected Gold params during live decisions.

## Furnace Boundary
- Furnace execution is part of cadence and telemetry, not direct trade authorization.
- Trade approval remains `Gatekeeper.decide(...)`; trade arm/fire lifecycle remains Brain Stem + Treasury.
- Furnace outcomes can influence trading only after a Gold mutation is written to vault and Soul hot-reloads.

## Operational Invariants
- One shared `BrainFrame` is the source of truth inside the cycle.
- Lobe order is deterministic for dependency correctness.
- Cycle exceptions should be contained and logged with lobe context.
- Timing metrics must be appended to pulse log for observability.

## Known Drift and Risks
- none identified (timing guards and trade-gate centralization resolved 2026-02-20)

## Testing Expectations
Minimum coverage:
- lobe order and frame mutation flow
- trade-gate inhibition behavior
- ACTION->MINT deferred execution flow via Brain Stem
- deadline metric capture
- failure containment per-lobe
