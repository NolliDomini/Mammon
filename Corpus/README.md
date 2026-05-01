# Corpus — Neural Bridge

Transport and synthesis layer: OpticalTract fans OHLCV data to all subscribers; Callosum blends Left and Right hemisphere signals into a final tier_score.

## Role

Two distinct responsibilities: `OpticalTract` is a synchronous broadcast bus that delivers each pulse DataFrame to every registered subscriber (lobes with `on_data_received`). `Callosum` is a deterministic blending function that merges `monte_score` (Left) and `tier1_signal` (Right) into `frame.risk.tier_score` during ACTION pulses.

## What It Does

- `OpticalTract.spray()` iterates subscribers in registration order, calls `on_data_received(df)`, catches exceptions per-subscriber so one failure doesn't block others
- `Callosum.score_tier()` computes `tier_score = clamp((monte × w_monte) + (tier1_signal × w_right), 0, 1)` and writes to `frame.risk.tier_score`
- Callosum logs every score to `callosum_mint` table for audit
- OpticalTract tracks per-subscriber delivery stats

## Files

- `callosum/service.py` — `Callosum`; `score_tier()` synthesis + `callosum_mint` logging
- `Optical_Tract/spray.py` — `OpticalTract`; subscribe/unsubscribe/spray broadcast bus
