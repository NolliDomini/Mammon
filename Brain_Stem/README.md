# Brain_Stem — Trigger

Final execution layer: arms trades at ACTION and fires physical orders at MINT.

## Role

Runs at ACTION and MINT pulses only. On ACTION, passes three gates (Risk Monte, Valuation Z-cap, Prior conviction) and arms a `pending_entry`. On MINT, either fires the order or cancels it (stale price guard, mean-deviation kill-switch). Manages exit logic (stop / take-profit bands) for open positions.

## What It Does

- **Gate 1 — Risk**: 1k-path Monte Carlo on current price; must exceed `brain_stem_min_risk` (default 0.65)
- **Gate 2 — Valuation**: 10k-path stddev simulation; entry z-score must be ≤ `brain_stem_entry_max_z` (default 0.8)
- **Gate 3 — Prior**: blended conviction `(monte_score × w_turtle) + (council × w_council)` must exceed 0.5
- **ACTION arm**: records `intent_id` in `money_orders` via TreasuryGland; sets `pending_entry`
- **MINT fire**: checks stale-price and mean-deviation guards, then calls `_fire_physical()` → Alpaca or mock
- **Exit**: compares price against entry bands (`lower = mean − 1.5σ`, `upper = mean + 2σ`); calls SELL when hit
- Recovers open position from TreasuryGland on engine restart

## BrainFrame I/O

- **Reads:** `frame.structure.price`, `frame.structure.active_lo`, `frame.environment.atr`, `frame.environment.confidence`, `frame.risk.monte_score`, `frame.command.sizing_mult`, `frame.command.ready_to_fire`, `frame.command.approved`
- **Writes:** `frame.risk.monte_score` (risk gate result), `frame.valuation.*` (mean, sigma, bands, z_distance)

## Key Config

| Param | Default | Purpose |
|---|---|---|
| `brain_stem_min_risk` | 0.65 | Risk gate floor (independent of Gatekeeper) |
| `brain_stem_entry_max_z` | 0.8 | Max z-score above fair value to enter |
| `brain_stem_stale_price_cancel_bps` | 25.0 | Cancel if price moves this many bps between ARM and FIRE |
| `brain_stem_sigma` | 0.10 | Noise scalar for both Monte runs |
| `brain_stem_bias` | 0.05 | Conviction bias injected into simulations |
| `brain_stem_w_turtle` | 0.5 | Weight on monte_score for Prior |
| `brain_stem_w_council` | 0.5 | Weight on council confidence for Prior |

## Files

- `trigger/service.py` — `Trigger` class; full ARM/FIRE/EXIT/HOLD logic
- `pons_execution_cost/service.py` — `PonsExecutionCost`; estimates slippage + fee in bps before sizing
