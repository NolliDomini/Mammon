# Cerebellum/council/spread_engine — SpreadEngine

Evaluates bid/ask friction and writes a normalized spread score to BrainFrame each SEED and ACTION pulse.

## Role

The 5th Council indicator. Runs before ATR/ADX/VWAP so its score can feed the `vol` slot in Council's weighted blend. If live bid/ask are unavailable or invalid, falls back to an ATR-proportional estimate.

## What It Does

- **Pulse gate**: skips MINT pulses entirely
- **Live path**: reads `bid`/`ask` from `frame.market.ohlcv`, computes spread in basis points, normalizes against ATR
- **ATR fallback**: when bid/ask are missing or invalid, estimates spread as `(ATR / close) × 10000 × spread_atr_ratio`
- **Score**: `1.0 − clamp(spread_bps / (atr_bps × scalar), 0, 1)` — higher is better (tighter spread)
- **Regime**: bins spread into TIGHT / NORMAL / WIDE / STRESSED using configurable bps thresholds
- Emits `COUNCIL-E-SPR-701` MNER only for invalid quotes (bid ≤ 0 or ask < bid); missing inputs use ATR fallback silently

## BrainFrame I/O

- **Reads:** `frame.market.ohlcv` (bid, ask, close), `frame.environment.atr`, `frame.standards`
- **Writes:** `frame.environment.bid_ask_bps`, `frame.environment.spread_score`, `frame.environment.spread_regime`, `frame.environment.spread_inputs`

## Key Config

| Param | Default | Purpose |
|---|---|---|
| `spread_atr_ratio` | 0.10 | ATR fraction used for fallback spread estimate |
| `spread_score_scalar` | 1.0 | Scales ATR denominator in score formula |
| `spread_tight_threshold_bps` | 5.0 | TIGHT regime ceiling |
| `spread_normal_threshold_bps` | 15.0 | NORMAL regime ceiling |
| `spread_wide_threshold_bps` | 50.0 | WIDE regime ceiling |

## Files

- `service.py` — `SpreadEngine`; evaluate(), ATR fallback, score + regime calculation
