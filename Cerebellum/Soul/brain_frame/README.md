# Cerebellum/Soul/brain_frame — BrainFrame

Zero-copy shared state object passed by reference through every lobe each pulse.

## Role

BrainFrame is the single source of truth for one pulse. All lobes read their inputs from and write their outputs to BrainFrame slots, eliminating inter-lobe data copying. Soul owns the frame lifecycle; lobes only write to their designated slot.

## What It Does

- Seven typed slots: `MarketDataSlot`, `StructureSlot`, `RiskSlot`, `EnvironmentSlot`, `ValuationSlot`, `ExecutionSlot`, `CommandSlot`
- `reset_pulse(pulse_type)` clears ephemeral state at the start of each pulse while preserving carry-forward context (spread values carry from ACTION to MINT)
- `generate_machine_code()` returns a 16-char SHA-256 hash of mode + pulse + symbol + regime + decision + ts for deduplication
- `to_synapse_dict()` flattens the entire frame into a flat dict for Amygdala persistence and Redis publishing
- `frame.standards` mirrors the current Gold params dict (set by Soul)

## BrainFrame I/O

- **Reads:** written by all lobes, read by all lobes
- **Writes:** Soul writes `market.*` and `standards`; each lobe writes only its designated slot

## Slot Owners

| Slot | Owner |
|---|---|
| `market` | Soul (orchestrator) |
| `structure` | Right_Hemisphere/SnappingTurtle |
| `risk` | Left_Hemisphere/TurtleMonte + Council (regime_id) |
| `environment` | Council + SpreadEngine |
| `valuation` | Brain_Stem/Trigger |
| `execution` | Brain_Stem/PonsExecutionCost |
| `command` | Medulla/Gatekeeper + AllocationGland |

## Files

- `service.py` — `BrainFrame` dataclass with all slots, `reset_pulse()`, `to_synapse_dict()`
