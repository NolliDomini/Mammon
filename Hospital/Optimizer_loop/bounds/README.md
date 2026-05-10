# Optimizer Bounds

## Purpose

Defines the 24-dimensional optimizer search space: `MINS`, `MAXS`, weight normalization, and the vectorized fitness kernel.

## Search Space (24-D)

| Index | Key | Min | Max | Notes |
|---|---|---|---|---|
| 0 | active_gear | 5 | 60 | SnappingTurtle lookback window (bars) |
| 1 | monte_noise_scalar | 0.05 | 2.0 | ATR multiplier for TurtleMonte noise |
| 2 | monte_w_worst | 0.0 | 1.0 | Weight on worst-lane survival |
| 3 | monte_w_neutral | 0.0 | 1.0 | Weight on neutral-lane survival |
| 4 | monte_w_best | 0.0 | 1.0 | Weight on best-lane survival |
| 5 | council_w_atr | 0.0 | 1.0 | Council ATR confidence weight |
| 6 | council_w_adx | 0.0 | 1.0 | Council ADX confidence weight |
| 7 | council_w_vol | 0.0 | 1.0 | Council volume confidence weight |
| 8 | council_w_vwap | 0.0 | 1.0 | Council VWAP confidence weight |
| 9 | gatekeeper_min_monte | 0.1 | 0.9 | Gatekeeper: minimum monte_score to approve |
| 10 | gatekeeper_min_council | 0.1 | 0.9 | Gatekeeper: minimum council confidence to approve |
| 11 | callosum_w_monte | 0.0 | 1.0 | Callosum blend weight on monte_score |
| 12 | callosum_w_right | 0.0 | 1.0 | Callosum blend weight on tier1_signal |
| 13 | brain_stem_w_turtle | 0.0 | 1.0 | Brain Stem prior: weight on monte_score |
| 14 | brain_stem_w_council | 0.0 | 1.0 | Brain Stem prior: weight on council confidence |
| 15 | brain_stem_sigma | 0.05 | 1.0 | Noise scalar for Brain Stem Monte runs |
| 16 | brain_stem_bias | 0.0 | 0.5 | Conviction bias injected into Brain Stem simulations |
| 17 | brain_stem_entry_max_z | 0.2 | 3.0 | Max z-score above fair value to enter |
| 18 | brain_stem_mean_dev_cancel_sigma | 0.0 | 5.0 | Cancel pending entry if price deviates this many σ |
| 19 | brain_stem_stale_price_cancel_bps | 0.0 | 250.0 | Cancel pending entry if price moves this many bps |
| 20 | brain_stem_mean_rev_target_sigma | 0.0 | 5.0 | Mean-reversion take-profit target in σ |
| 21 | stop_loss_mult | 1.5 | 12.0 | Stop loss ATR multiplier |
| 22 | breakeven_mult | 1.0 | 10.0 | Breakeven move ATR multiplier |
| 23 | brain_stem_min_risk | 0.40 | 0.70 | Brain Stem risk gate floor (independent of Gatekeeper) |

## Weight Groups

`normalize_weights(raw_row)` normalizes four groups to sum to 1:

| Group | Indices |
|---|---|
| Monte weights | 2–4 |
| Council weights | 5–8 |
| Callosum weights | 11–12 |
| Brain Stem blend weights | 13–14 |

Index 23 (`brain_stem_min_risk`) is a scalar threshold — not normalized.

## Fitness Kernel

`calculate_batch_fitness(scaled_batch, min_cumsum, dist_to_stop)` — vectorized, operates on batches of candidates:

1. Extracts `gears` (index 0) and `noise_scalars` (index 1)
2. Fetches survival rates for each candidate across 3 volatility lanes (worst ×2.0, neutral ×1.0, best ×0.5)
3. Computes `risk_score = w_worst×s_worst + w_neutral×s_neutral + w_best×s_best`
4. Applies gate penalty: `risk_score ≤ 0.5` → score ×0.5

This kernel is used in Stage A (LHS scan) and Stage F (focused refine). Monte weights (indices 2–4) are consumed from `scaled_batch` directly.
