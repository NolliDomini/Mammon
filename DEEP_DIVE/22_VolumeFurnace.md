# Deep Dive: VolumeFurnaceOrchestrator — Inline Live Optimizer

## 1. Purpose & Role

`VolumeFurnaceOrchestrator` is the **Hospital Stage A-H optimizer running inline inside the live Soul cycle**. It is instantiated by the Orchestrator at boot and called on every pulse via `handle_frame()`. It runs the full 8-stage parameter search pipeline (`OptimizerV2Engine`) periodically during live trading.

This is NOT a batch process. It shares the same Python process and thread as the live pulse loop.

---

## 2. When It Fires

`handle_frame()` is called every pulse. The cadence gates determine when actual optimization work runs:

```
Every pulse → pulse_count++
  │
  ├── pulse_type != "MINT" → CADENCE_GATE (skip), return
  │
  └── pulse_type == "MINT" → mint_count++
        │
        ├── mint_count % 3 != 0 → CADENCE_GATE (skip), return   ← 2 of every 3 MINTs skipped
        │
        └── activation_count++ → run pipeline
              │
              ├── activation_count % 4 == 0 → allow_bayesian = True   ← every 4th activation
              └── else → allow_bayesian = False
```

**Live cadence (DRY_RUN/PAPER/LIVE):**
- Fires on every **3rd MINT** → roughly every **15 minutes**
- Bayesian stage (Stage G) enabled every **4th activation** → roughly every **60 minutes**

**Simulation mode (BACKTEST):** fires every 4th scheduled activation (every 12th MINT).

---

## 3. The 8-Stage Pipeline (OptimizerV2Engine.run_pipeline)

| Stage | Name | Work |
|---|---|---|
| A | Edge LHS Scan | 64 random param candidates; fast `_approx_score` filter (keeps ≥ 0.35) |
| B | Semi-Middle Band | Keeps the 20th–80th percentile of Stage A — discards extremes |
| C | Candidate Library Fill | Expands top-6 survivors with 12 noisy neighbours each (~72 candidates) |
| D | Walk Context | Uses `walk_seed.mutations` as price shocks; falls back to ATR-derived noise |
| E | Vectorized Monte | Scores each candidate against price shocks — computes worst/neutral/best survival, stability, expectancy |
| F | Refine LHS | Takes best Stage E winner, samples 32 more in ±5% neighbourhood, re-scores |
| G | Bayesian Exploit | (every 4th activation) Score-weighted average of top-15 → one additional candidate with 1.05× score boost |
| H | Promotion Gate | Diversity check + GuardrailedOptimizer 7-threshold gate → `promoted: True/False` |

**Stage A `_approx_score` uses only 4 params:** `monte_w_worst`, `monte_w_neutral`, `monte_w_best` (risk tilt) and `council_w_atr` vs `council_w_vwap` (balance). 19 of 23 params are invisible to the fast filter.

**Stage E vectorized Monte uses:**
- `cand[0]` = `active_gear` — path length
- `cand[1]` = `monte_noise_scalar` — noise amplitude
- `cand[21]` = `stop_loss_mult` — stop floor
- `cand[18]` = `brain_stem_noise` — **slippage cost proxy** (`slippage_cost = cand[18] * 0.4`)

`brain_stem_noise` is a dead param — `trigger/service.py` never reads it. The optimizer penalizes candidates for high `brain_stem_noise` values as if it represents slippage, but this penalty has zero relationship to actual execution cost.

---

## 4. What Happens on Promotion

Stage H returns `(promoted: bool, reason: str)`. The result is written to `OptimizerLibrarian` audit tables (`optimizer_promotion_decisions`) and stored in `self.last_summary`.

**Critical finding: promotion never writes to the vault.**

`VolumeFurnaceOrchestrator` has no reference to `PituitaryGland` and calls no vault-write method. The `promoted=True` flag is audit-only. Winners are logged but params are never crowned as Platinum or Gold.

The batch Hospital optimizer (`Hospital/Optimizer_loop/service.py`) calls `pituitary.secrete_platinum()` on a winner — that code path is NOT wired from `VolumeFurnaceOrchestrator`. The inline live optimizer evaluates candidates but its results die in the audit tables.

---

## 5. Mutations / Walk Context (Stage D)

Stage D uses `walk_seed.mutations` as price shock sequences. These come from `QuantizedGeometricWalk.build_seed()`:

| Source | When |
|---|---|
| `frame.risk.shocks` (BACKTEST) | BACKTEST mode with shocks in frame |
| `scribe.discharge()` → silo | Walk prior available in DuckDB `walk_mint` |
| `frame.risk.shocks` (live fallback) | Previous pulse's mutations |
| `deterministic_fallback` | First pulse; 2048 normally-distributed values keyed on regime_id hash |

Since walk prior feedback is dead (see `17_WalkScribe.md`), `scribe.discharge()` always returns `[]`. After the first pulse, `frame.risk.shocks` carries the previous pulse's mutations — so the optimizer is scoring candidates against self-reinforcing previous-cycle shock distributions, not historical regime data.

---

## 6. `_approx_score` Bias

Stage A's fast filter pre-screens candidates using:
```python
risk_tilt = row[2]*0.2 + row[3]*0.4 + row[4]*0.4   # monte lane weights
balance   = 1.0 - abs(row[5] - row[8])               # council_w_atr vs council_w_vwap
penalty   = min(distance_to_stop * 0.03, 0.30)
score     = (0.55 * risk_tilt) + (0.35 * balance) - penalty
```

This pre-filter favours: (1) high `monte_w_neutral` and `monte_w_best` weights, (2) similar `council_w_atr` and `council_w_vwap`. Candidates with imbalanced Council weights or low neutral/best Monte weights are eliminated before Monte scoring. The population that reaches Stages E-H is already biased by this filter.

---

## 7. Resource Cost

At every 3rd MINT (~every 15 minutes), the Furnace runs:
- 64 random LHS samples (Stage A)
- ~72 candidates through vectorized Monte (Stage E, each scored against n_paths price paths)
- 32 refined candidates (Stage F, same Monte)
- Occasionally 15 more Bayesian candidates (Stage G)
- All audit writes to `OptimizerLibrarian` (DuckDB)

This is CPU and I/O work on the same thread as the live pulse loop. A slow optimizer pass could delay SEED→ACTION→MINT timing if the processing laps a pulse boundary.

---

## 8. OptimizerLibrarian vs the Main Librarian

`VolumeFurnaceOrchestrator` uses `OptimizerLibrarian` — a separate class from `MultiTransportLibrarian`. It writes to optimizer-specific tables in DuckDB (`optimizer_stage_runs`, `optimizer_candidates`, `optimizer_promotion_decisions`, etc.). These are separate from the synapse/vault tables the main system uses.

---

## 9. Non-Obvious Behavior

- **Furnace runs in live mode always.** Even DRY_RUN has `simulation_mode=False`. The optimizer fires every 15 minutes during normal DRY_RUN operation.
- **First activation is immediate.** On the 3rd MINT after engine start, the Furnace fires for the first time. It may fire with a warmup BrainFrame where `regime_id = "UNK"` — coerced to `"GLOBAL"` by `_coerce_context()`.
- **Promotion is an audit event, not a vault event.** The dashboard `furnace` event in the Neural Log shows `EXECUTED` or `PIPELINE_ERROR` from `_record_decision()`. `EXECUTED` means the pipeline ran and logged a promotion decision — not that params changed.
- **`brain_stem_noise` as slippage** is a design artifact. The param exists in PARAM_KEYS but is unused by Trigger. The optimizer treats it as a slippage scalar — effectively scoring candidates on a random dimension.
- **Furnace telemetry is visible to the dashboard.** `_publish_furnace_run_events()` in `dashboard.py` polls `orchestrator.furnace.telemetry` and surfaces `EXECUTED` / `PIPELINE_ERROR` events to the Neural Log. This is the only live optimizer visibility the dashboard provides.

---

## 10. Open Questions / Risks

- **Promotion is dead.** The entire inline optimizer pipeline produces winners that are never used. Should Stage H call `Pituitary.secrete_platinum()` directly, or should results be polled by the batch Hospital run?
- **Thread safety.** OptimizerLibrarian writes to DuckDB (analytical store). The main Thalamus and DuckPond also write to DuckDB. The inline optimizer adds a third DuckDB writer in the same process. Single DuckDB write lock still applies.
- **Slow pipeline on live thread.** No timeout or deadline on `engine.run_pipeline()`. A slow Bayesian stage could hold the pulse processing thread past the next 5-minute boundary.
- **Mutations are self-reinforcing after first pulse.** Stage D uses previous pulse's shocks once silo is empty. The optimizer converges on parameter regions that score well against its own previous output — a closed feedback loop with no market ground truth.
