# Snapping Turtle

## Purpose
Snapping Turtle is the Right Hemisphere structure painter.

It owns:
- Donchian breakout structure painting on `frame.structure`
- deterministic strike provenance when breakout is true
- lobe-level paint telemetry (`last_paint_event`)

It does not own:
- pulse sequencing authority
- policy or approval decisions
- DB writes or execution actions

## Runtime Contract
- Active signature: `on_data_received(pulse_type, frame)`
- Input source: `frame.market.ohlcv`
- Output side effect: writes only to `frame.structure`

Structure fields updated:
- `active_hi`
- `active_lo`
- `gear`
- `tier1_signal`
- `price`

## Fail-Safe Behavior
- If required columns are missing, values are non-numeric, frame is empty, gear is invalid, or history is insufficient:
  - `tier1_signal` is forced to `0`
  - structure fields are reset to safe values
  - `last_paint_event.status` is updated with deterministic reason code
