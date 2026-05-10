# Optimizer V2

## Purpose

Runs the Stage A-H candidate search and guardrailed promotion evaluation. Called by VolumeFurnaceOrchestrator on every eligible MINT cadence tick.

## Ownership

- Stage A-H candidate generation, scoring, and promotion
- Robust score computation and diversity enforcement
- Promotion pass/fail reason coding
- Telemetry persistence via OptimizerLibrarian

## Anti-Ownership

- Does not execute trades
- Does not override policy gates
- Does not install Gold params into vault directly

## PARAM_KEYS (24 parameters)

```
0:  active_gear
1:  monte_noise_scalar
2:  monte_w_worst
3:  monte_w_neutral
4:  monte_w_best
5:  council_w_atr
6:  council_w_adx
7:  council_w_vol
8:  council_w_vwap
9:  gatekeeper_min_monte
10: gatekeeper_min_council
11: callosum_w_monte
12: callosum_w_right
13: brain_stem_w_turtle
14: brain_stem_w_council
15: brain_stem_sigma
16: brain_stem_bias
17: brain_stem_entry_max_z
18: brain_stem_mean_dev_cancel_sigma
19: brain_stem_stale_price_cancel_bps
20: brain_stem_mean_rev_target_sigma
21: stop_loss_mult
22: breakeven_mult
23: brain_stem_min_risk
```

`_row_to_params(row)` zips PARAM_KEYS with the numpy row to produce the Gold param dict.

## V2Budget Defaults

| Field | Default | Purpose |
|---|---|---|
| edge_lhs_n | 64 | Stage A LHS sample size |
| island_n | 12 | Stage C island candidates |
| top_k | 6 | Top candidates kept per island cycle |
| refine_lhs_n | 32 | Stage F focused LHS sample size |
| bayes_n | 15 | Stage G Bayesian exploit draws |
| min_support | 35 | Stage D minimum walk support floor |
| diversity_floor | 0.05 | Minimum normalized distance between promoted candidates |

## Stage Summary

| Stage | Name | What it does |
|---|---|---|
| A | Edge LHS Scan | Latin hypercube samples `edge_lhs_n` candidates, scores via `calculate_batch_fitness` |
| B | Band Extract | Extracts semi-middle band from walk context (price/ATR/stop) |
| C | Island Fill | Generates `island_n` candidates around centroid of top-k; fills candidate library |
| D | Walk Context | Applies regime mutations and validates support floor against walk history |
| E | Vectorized Monte | Scores all candidates using full Monte survival simulation |
| F | Focused Refine | LHS resample around best survivors; re-scores |
| G | Bayesian Exploit | Draws `bayes_n` candidates from Gaussian around top performers; re-scores |
| H | Promotion Gate | Checks robust_score, drawdown, stability, slippage, support, diversity; marks winner |

## Promotion Output

`run_pipeline()` returns a dict including:
- `promoted` (bool)
- `winner_candidate_id`
- `winner_robust_score`
- `promotion_reason` (pass/fail code)
- Stage-level telemetry

## Files

- `service.py` — `OptimizerV2Engine`, `V2Budget`, `PARAM_KEYS`
