# Brain Stem Internal Logic

## Scope
This document reflects current execution-path internals in `Brain_Stem/connection.py`.

## Core Entry Point
- `Trigger.load_and_hunt(pulse_type, frame, orchestrator=None, walk_seed=None)`

Primary lifecycle:
1. Validate pulse and command eligibility (`frame.command.ready_to_fire`, pulse type rules).
2. Arm intent on ACTION when policy is green.
3. Finalize on MINT (fire, cancel, reject, or timeout path).
4. Persist lifecycle transitions to Treasury-backed ledgers.

## Internal Gates (Current State)
Current implementation contains execution safety checks:
- risk gate simulation
- valuation/fair-value style gate

These gates run before broker/mock fire path as final execution safety.
Gatekeeper fire-eligibility remains required before ACTION arm.

## Adapter Routing
Mode-driven adapter path:
- `DRY_RUN`/`BACKTEST`: mock execution adapter
- `PAPER`/`LIVE`: broker adapter path (Alpaca helpers)

Runtime trade gate from orchestrator can inhibit pending intents and force cancel path.

## State and Persistence
Brain Stem tracks transient execution state including:
- pending entry intent
- open/closing position metadata
- inhibition/exit reasons

Terminal lifecycle writes flow to Treasury ledgers (`money_orders`, related fills/audit tables).

## Invariants
- Intent lifecycle must terminate with explicit status.
- No silent success on adapter failure.
- Mode and trade-gate controls must be honored before any fire.
- Gatekeeper policy ownership is preserved: Brain Stem does not independently approve.

## Runtime Notes
- Mode-rebind consistency during runtime mode switches is implemented in the active runtime path.
- Execution telemetry now includes per-transition event context (`pulse`, `mode`, `adapter`, transition, reason).
