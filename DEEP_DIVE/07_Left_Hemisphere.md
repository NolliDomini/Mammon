# Deep Dive: Left Hemisphere — Risk Engine

## 1. Purpose & Role
Left Hemisphere is the **probabilistic risk engine**. It runs vectorized Monte Carlo simulations to determine the probability that price survives above the stop level over a forward window. The output (`monte_score`) is Brain Stem's Gate 1 and the `prior` conviction blending input.

Two components work together:
- **QuantizedGeometricWalk** — builds a calibrated `WalkSeed` from Council state (called by Soul directly)
- **TurtleMonte** — runs the simulation using that seed, writes `frame.risk`

---

## 2. Inputs & Outputs

**WalkSeed inputs** (from Council state + frame):
- `frame.structure.price`, `frame.environment.atr`
- `council_state` dict (confidence, adx, atr, volume, avwap)

**TurtleMonte inputs** (from frame + walk_seed):
- `frame.structure.price` — current price
- `frame.structure.active_lo` — stop level (Donchian low)
- `frame.environment.atr` — volatility
- `frame.structure.gear` — n_steps for simulation
- `frame.risk.shocks/mutations` — historical noise vectors

**Writes to `frame.risk`:**
| Field | Value |
|---|---|
| `monte_score` | Weighted survival probability (0–1) |
| `worst_survival` | Lane 0 survival rate (2× noise) |
| `neutral_survival` | Lane 1 survival rate (1× noise) |
| `best_survival` | Lane 2 survival rate (0.5× noise) |
| `lane_survivals` | `[worst, neutral, best]` |
| `mu`, `sigma`, `p_jump`, `regime_id`, `shocks`, `mutations` | From WalkSeed |

---

## 3. The Simulation

```
paths_per_lane = 10,000  (default)
total_paths    = 30,000  (3 lanes × 10k)
n_steps        = active_gear (currently 3)

Lane noise multipliers: [2.0×, 1.0×, 0.5×]  (worst, neutral, best)

noise shape: (30000, n_steps)
  = historical shocks (tiled) OR deterministic fallback
  × (atr × noise_scalar × sigma_mult) × lane_mult

paths = current_price + cumsum(noise, axis=1)
hit_stop = any(paths <= active_lo, axis=1)
survival_rate[lane] = mean(~hit_stop per lane)

monte_score = sum(rates × lane_weights) / sum(lane_weights)
```

Default lane weights: `[0.15, 0.35, 0.50]` — best-case lane has 3.3× the weight of worst.

---

## 4. WalkSeed — Regime-Keyed Trajectory Prior

`QuantizedGeometricWalk.build_seed()` does three things:
1. Computes `regime_id` (D_A_V_T string — same 4-dimension scheme as Council)
2. Derives `mu`, `sigma`, `p_jump` from Council metrics
3. Provides `mutations` — historical noise vectors for shock injection

**Mutation source priority:**
1. Walk Silo discharge (`WalkScribe.discharge(regime_id, limit=35000)`) — live mode
2. `frame.risk.shocks` — backtest or fallback
3. Deterministic RNG seeded by `hash(regime_id|mode|pulse_type)` — last resort

**mu formula:** `trend_score × 0.1 × (1.0 if above VWAP else -0.2)` — tiny directional drift, penalized if price is below VWAP.

**p_jump:** `0.05` if vol_ratio > 1.5 AND atr_ratio > 1.2, else `0.01`.

---

## 5. Soul Call Sequence

```
Soul._process_frame():
  → Left_Hemisphere.on_data_received()  # fast pass — validates frame, returns True
  → walk_engine.build_seed()            # WalkSeed built, writes frame.risk priors
  → if tier1_signal == 1 and ACTION:
      → Left_Hemisphere.simulate()      # full 30k-path Monte, writes frame.risk scores
  → if tier1_signal == 1 and SEED:
      → Left_Hemisphere.simulate()      # early window simulation
```

`on_data_received` is a **no-op** (just validates frame, returns True). All real work is in `simulate()`.

---

## 6. Dependencies

| Dependency | Direction | Purpose |
|---|---|---|
| `BrainFrame` | read/write | Source data + risk slot writes |
| `WalkScribe` | outbound | Reads historical shocks from Walk Silo |
| `Hippocampus.Archivist.Librarian` | outbound | Logs simulation results to `turtle_monte_mint` and `quantized_walk_mint` |
| `Council.get_state()` | inbound | Council state dict passed to `build_seed()` |

---

## 7. Failure Modes

- **Invalid gear, price, ATR, or stop level**: `_safe_risk_reset()` — all risk scores → 0.0, simulation skipped
- **Missing shocks**: deterministic fallback RNG — seeded by regime_id hash, reproducible
- **Simulation log failure**: silently swallowed — audit only, never blocks
- **Walk Silo unavailable**: falls through to frame_shocks or deterministic fallback

---

## 8. Non-Obvious Behavior

- **Stop level = `active_lo` (Donchian low)** — the Monte Carlo is literally asking "does price stay above the breakout floor?" Not a fixed stop-loss distance.
- **Lane weights skew heavily toward best-case.** `[0.15, 0.35, 0.50]` means the score is optimistic by design — the best-lane (lowest noise) has 50% of the final weight.
- **Shock injection tiles historical mutations to fill `(30000 × n_steps)`** — if silo returns fewer shocks than needed, `np.resize` wraps around. At gear=3, 35,000 shocks → tiled across 90,000 elements with repetition.
- **Jump diffusion is additive, not multiplicative.** Jumps add normal noise at `atr × sigma_mult` scale to paths that hit the jump mask — not fat-tailed Lévy jumps.
- **`mu` is near-zero by design** (`trend_score × 0.1`) — the walk has minimal drift. The simulation is primarily testing volatility survival, not directional prediction.
- **Two separate regime_id calculations exist** — one in Council (`D_A_V_T` with 4 bins), one in QuantizedGeometricWalk (same structure, different bin thresholds). They can produce different IDs for the same market state.

---

## 9. Open Questions / Risks

- **Regime ID divergence**: Council and QuantizedGeometricWalk use the same D_A_V_T structure but different binning thresholds — the `regime_id` written to `frame.risk` by Council may not match the one in the WalkSeed.
- **Best-lane dominance**: 50% weight on the best-case lane means the system can be optimistic in volatile regimes — monte_score can stay high even when worst-lane survival collapses.
- **Walk Silo freshness**: `WalkScribe.discharge()` pulls up to 35,000 mutations — if the silo is stale or empty, the deterministic fallback produces identical noise every pulse for a given regime, eliminating path diversity.
- **n_steps = gear = 3**: extremely short forward window. 3 steps of noise from `active_lo` is a very tight test — small ATR moves dominate.

---

## 10. Deep Investigation: WalkSeed Mutation Self-Reinforcement

### The Fallback Chain (confirmed from `Left_Hemisphere/Monte_Carlo/walk/service.py`)

`QuantizedGeometricWalk.build_seed()` selects mutations via priority:

```
1. BACKTEST with frame.risk.shocks      → frame_shocks
2. WalkScribe.discharge(regime_id)      → silo
3. frame.risk.shocks (live fallback)    → frame_live
4. deterministic RNG (hash of regime_id|mode|pulse_type) → deterministic_fallback
```

### What Actually Happens

**Step 2 is permanently dead.** `WalkScribe.discharge()` reads from DuckDB `walk_mint` — a table that has no write path in production (`TurtleWalk._mint_seed()` calls `self.librarian.dispatch()` which does not exist on `Librarian`, raising a silent `AttributeError`). Discharge always returns `[]`. (See `17_WalkScribe.md` for full failure chain.)

**First pulse:** `frame.risk.shocks` is empty at boot. Falls through to step 4 — deterministic fallback. `2048` normally-distributed values seeded by `hash(regime_id | mode | pulse_type)`. Reproducible, but has no relationship to actual market volatility for that regime.

**Every subsequent pulse:** `frame.risk.shocks` carries the mutations from the previous pulse (the `frame_live` path). The Walk Engine wrote mutations from the last `build_seed()` call into `frame.risk.shocks`. The next pulse reads them back as its shock inputs.

### The Consequence

After pulse 1, the Monte Carlo is scoring survival against noise derived from its own previous output — a closed feedback loop. The system cannot incorporate real historical regime volatility (silo is dead). It cannot be seeded from backtest shocks in live mode. Each pulse's Monte simulation is calibrated against the drift of the previous pulse's simulation.

If the previous pulse's shocks were optimistic (low variance, high survival), the next pulse's Monte will also be optimistic. The system can drift toward a self-reinforcing bullish bias in the noise distribution with no market anchor to correct it.

**`shock_source = "silo_discharge"` is never reached in live operation.** The Monte Carlo always runs on deterministic fallback (first pulse) or previous-pulse recycled mutations (every subsequent pulse).

---

## 11. Deep Investigation: `regime_id` Overwrite Sequence

Two components both write `frame.risk.regime_id` within the same `_process_frame()` call:

**Step 1 — Council writes it:**
`Council.consult()` computes D_A_V_T using its own bin thresholds and sets:
```python
frame.risk.regime_id = "D2_A1_V3_T2"   # Council's binning
```

**Step 2 — TurtleWalk overwrites it:**
`walk_engine.build_seed()` runs after Council. `QuantizedGeometricWalk` computes its own D_A_V_T using **different bin thresholds** and writes:
```python
frame.risk.regime_id = "D1_A2_V2_T3"   # TurtleWalk's binning (may differ)
```

The `frame.risk.regime_id` that reaches `_frame_to_event()` and the dashboard is **TurtleWalk's version**, not Council's. The two can produce different strings for the same market state because they use different boundary values for each dimension.

`07_Left_Hemisphere.md` Section 8 documents that divergence is possible. The addition here: **TurtleWalk always wins** — it is called second, its write is final.

Practical consequence: the `regime_id` used to key the Walk Silo discharge (`WalkScribe.discharge(regime_id)`) and the `regime_id` used by Council's `regime_weight_table` override are derived from different binning functions. A parameter set that Council identifies as matching regime `D2_A1_V3_T2` may be keyed differently in Walk Silo history under TurtleWalk's binning. The two systems effectively speak different dialects of the same regime language.
