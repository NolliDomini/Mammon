# Left Hemisphere Monte

## Purpose
Left Hemisphere is Mammon's risk trajectory painter/consumer.

It owns:
- regime prior painting to `frame.risk` (`mu`, `sigma`, `p_jump`, `shocks`, `regime_id`)
- Monte survival simulation from frame-owned risk priors
- risk-slot outputs (`monte_score`, lane survivals)

It does not own:
- pulse sequencing authority
- policy approval decisions
- execution actions

## Runtime Contracts
- Walk: `QuantizedGeometricWalk.build_seed(..., frame=frame)` paints priors on `frame.risk` every cycle.
- Monte: `TurtleMonte.simulate(pulse_type, frame, walk_seed=None)` consumes `frame.risk` priors as first-class inputs.

## Safety and Determinism
- Invalid risk context (`gear`, `atr`, `stop`) returns deterministic safe output (`monte_score=0`).
- Shock policy:
  - `BACKTEST`: uses frame-provided historical shocks when available.
  - `LIVE/other`: uses frame/silo shocks when available.
  - fallback: deterministic seeded generation when shock buffers are missing.
