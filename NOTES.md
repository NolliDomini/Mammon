# Mammon — Running Notes

## 2026-04-24 — Dry Run Observations

### Low Volume (Thalamus / Council)
`volume_score` is consistently near zero (0.001–0.015) across all recent pulses.
Alpaca is reporting thin crypto volume at this time of day.
This is suppressing `council_score` (currently 0.37–0.42, below the 0.44 min threshold)
and contributing to WAITING decisions even when other signals are acceptable.

**Watch:** council_score during higher-volume sessions (US market hours, major crypto sessions)
to confirm this is a time-of-day effect and not a structural scoring issue.

### Corpus Callosum — Stale tier_score in frame
`reset_pulse()` does not clear `frame.risk`, so `tier_score` persists across pulses.
When Turtle fires but Monte is cold (atr=0), Callosum writes `(0 × w_monte) + (1 × w_right) = 0.3`
and that value sits in the frame until the next time Callosum runs. Noise in synapse records.

### Optical Tract — 50ms Budget Not Enforced
Delivery budget of 50ms is tracked in `delivery_stats` but never enforced — no timeout or
warning fires if a lobe runs long. Not a problem at 5-minute pulse intervals, but worth
enforcing if cadence ever tightens (e.g. 1m pulses).

### AllocationGland — Two Bugs Fixed (2026-04-24)
**Bug 1 — Ordering:** AllocationGland ran before Brain Stem set `frame.valuation.z_distance`.
Brain Stem only sets z_distance inside `load_and_hunt`. AllocationGland always saw z_distance=0.0
(reset-cleared) → triggered `NO_TRADE_ABOVE_MEAN` → silently zeroed `frame.command.ready_to_fire`
and `approved`, killing Gatekeeper-approved trades. Observed at 17:50 and 18:30 UTC.

**Bug 2 — Field mismatch:** AllocationGland wrote `frame.command.qty` but Brain Stem exclusively
reads `frame.command.sizing_mult`. AllocationGland's sizing calculation had zero effect on what
Brain Stem actually fired; it could only suppress (never contribute).

**Fix:** Orchestrator now gates AllocationGland behind `frame.command.ready_to_fire` and
pre-computes Brain Stem's valuation gate before AllocationGland runs, so z_distance is live.
AllocationGland now also writes `sizing_mult` so its refined quantity reaches Brain Stem.

**Bug 3 — Sign inversion + field name in Brain Stem (fixed same session):** Brain Stem wrote
`(price - mean) / sigma` → z_distance was negative when price was below mean (good entry).
Correct formula per contract tests, TheBrain migration, and AllocationGland design:
`z_distance = (mean - price) / sigma` — positive when underpriced, zero/negative when at/above mean.
Also: Brain Stem was writing `frame.valuation.sigma` (doesn't exist on ValuationSlot) instead
of `frame.valuation.std_dev`, and omitting `valuation_source = "TRIGGER_GATE"`. All three fixed
in `Brain_Stem/trigger/service.py` and in the orchestrator's pre-compute block.

### PonsExecutionCost — Impact dead, fee always 30bps (2026-04-25)
Two structural gaps (not bugs, but worth knowing):

**Impact always 0:** `impact_bps` uses `frame.command.notional` which is 0 at Pons runtime —
Gatekeeper/AllocationGland run after Pons, so notional hasn't been set yet. The square-root
impact model is implemented correctly but its input is never available. `slippage_impact_scalar`
param is effectively unused.

**Fee always 30bps fallback:** Gold params contain no `fee_taker_bps` or `fee_fallback_pct`,
so Pons always hits the ultra-pessimistic 30bps hardcoded fallback. AllocationGland's cost penalty
is therefore always 30% of max (30/100). Add `fee_taker_bps` to Gold vault params to fix.
