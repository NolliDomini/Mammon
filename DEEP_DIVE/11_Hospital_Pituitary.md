# Deep Dive: Hospital + Pituitary — The Evolutionary Engine

These two modules form the **self-optimization loop**. Hospital discovers good parameters through Monte Carlo search; Pituitary refines them through Gaussian Process regression and installs the result as the live Gold standard.

---

## Hospital — The Volume Furnace

### Purpose
Runs a staged parameter discovery pipeline every 3rd MINT pulse, searching for `robust_score`-maximizing parameter vectors for the current market regime.

### Cadence
```
VolumeFurnaceOrchestrator.handle_frame() called every pulse by Soul
  → only executes on MINT
  → cadence gate: every 3rd MINT (live)
  → Bayesian stage: every 4th activation
```

### Stage A–H Pipeline

| Stage | What it does |
|---|---|
| **A** Edge LHS | Latin Hypercube sample of parameter space near regime edges |
| **B** Semi-middle band | Filters to candidates in the middle performance band |
| **C** Candidate library fill | Augments with historical Silver candidates from DB |
| **D** Walk context | Pulls `mutations` from WalkSeed for shock injection |
| **E** Vectorized Monte | Scores all candidates via survival simulation (60 steps, 3 lanes) |
| **F** Refine LHS | Local LHS refinement around top Stage E survivors |
| **G** Bayesian exploit | GP-guided exploitation of high-fitness region (every 4th activation) |
| **H** Promotion gate | Diversity floor + risk gate (`robust_score >= 0.5`) check before promoting winner |

Any stage returning empty aborts the pipeline (`status: "skipped"`).

### Fitness Scoring (Stage E `ScoreVector`)
```
robust_score = f(expectancy, survival, stability, drawdown, uncertainty, slippage_cost, score_std)
```
- `survival` = neutral-lane path survival above stop floor
- `stability` = `1 - std([worst, neutral, best])` — penalizes lane divergence
- `expectancy` = `clip(0.5 + mean_terminal_return_pct, 0, 1)`
- `slippage_cost` = `cand[18] × 0.4` — param index 18 is `slippage_impact_scalar`

### Parameter Space
23-D vector (same keys as Pituitary PARAM_KEYS). Bounds defined in `Hospital/Optimizer_loop/bounds.py`.

### Output
If Stage H promotes a winner: calls `Pituitary.secrete_platinum()` → writes to `platinum_params.json`. Does **not** directly update Gold — that's Pituitary's job.

---

## Pituitary — The Master Hormonal Controller

### Purpose
Every 4th MINT, runs Gaussian Process regression over the Gold/Silver/Platinum tier params to mathematically derive a new Gold standard and install it into `hormonal_vault.json`.

### Hormone Hierarchy

| Tier | Source | Role |
|---|---|---|
| **Platinum** | Hospital `secrete_platinum()` | Bleeding-edge optimizer winner |
| **Gold** | Pituitary GP mutation | Active live reference — what Soul loads |
| **Silver** | Synapse memory mining (`final_confidence > 0.8`) | Historical high-conviction winners |
| **Bronze** | Demoted Gold entries | Genealogy log (rolling 10 in vault, 100 in file) |

### GP Mutation Cycle (`secrete_growth_hormone` → `_run_gp_mutation`)
```
Every 4th MINT:
  1. Load Platinum (file), Gold (vault), Silver (vault)
  2. Build training data: X = 23-D param vectors, y = fitness scores
  3. Fit Matern(ν=1.5) GP on ≥2 tiers
  4. Sample 500 random candidates within bounds
  5. Normalize weight groups on each candidate
  6. Predict fitness → select argmax
  7. Clamp to Diamond safety rails (from vault["diamond_rails"])
  8. Integrity gate (Piece 14): all 23 keys present, within MINS/MAXS
  9. Coronation: old Gold → bronze_history, new GP-derived params → Gold
  10. Clear Silver (consumed), save vault
```

### Integrity Gate (Piece 14)
Hard check before any coronation: all 23 PARAM_KEYS present, each value within `MINS[i]` to `MAXS[i]`. Failure aborts the coronation — old Gold survives.

### Diamond Safety Rails
`vault["diamond_rails"]["bounds"]` — per-param min/max bounds derived by Bayesian search over synapse history (DiamondGland, `Pituitary/search/diamond.py`). Applied as a clamping step after GP prediction.

---

## Full Optimization Flow

```
Every pulse:
  Soul → VolumeFurnaceOrchestrator.handle_frame()
    → every 3rd MINT: run Stage A-H pipeline
        → if winner passes Stage H: Pituitary.secrete_platinum()

Every pulse:
  Soul → Pituitary.secrete_growth_hormone()
    → every 4th MINT: run GP mutation
        → if valid: install new Gold into hormonal_vault.json

Every MINT:
  Soul → _check_vault_mutation()
    → if Gold ID changed: hot-reload all lobes with new params
```

The two cadences are independent — Hospital fires every 3rd MINT, Pituitary GP every 4th. They don't coordinate directly; Platinum written by Hospital becomes available for Pituitary's next GP cycle.

---

## Dependencies

| Dependency | Direction | Purpose |
|---|---|---|
| `BrainFrame` (via Soul) | inbound | regime_id, price, atr, stop_level, walk_seed |
| `WalkSeed.mutations` | inbound | Shock vectors for Stage E Monte |
| `OptimizerLibrarian` | outbound | Stage run logs, candidate library, diversity metrics |
| `hormonal_vault.json` | read/write | Gold tier source of truth |
| `platinum_params.json` | read/write | Platinum tier |
| `Ecosystem_Synapse.db` | inbound | Silver mining (high-confidence MINT rows) |
| `sklearn.GaussianProcessRegressor` | internal | Matern GP fit |

---

## Non-Obvious Behavior

- **Hospital never writes Gold directly.** It writes Platinum; Pituitary GP promotes Platinum to Gold on the next 4th-MINT cycle. There's a lag between a Hospital discovery and Gold deployment.
- **Pituitary GP needs ≥2 tiers.** If Silver is `None` (consumed last cycle) and Platinum doesn't exist, only Gold is available → GP skipped. A fresh install with no history will stall the evolution cycle.
- **Silver is consumed on each GP run.** After GP mutation, `vault["silver"] = None`. Silver only comes back when a new high-confidence synapse ticket is written.
- **`secrete_growth_hormone` is called every pulse**, not just MINT — but returns early on non-MINT. This means a call overhead every SEED and ACTION.
- **Hot-reload triggers on Gold ID change.** Since Pituitary writes `id: "gp_mutation_{timestamp}"`, every GP coronation triggers a full lobe reload at the next MINT's `_check_vault_mutation()` check.

---

## Open Questions / Risks

- **No fitness ground truth.** GP trains on `fitness_snapshot` from Gold and `fitness_estimate` from Platinum/Silver — these are predicted scores from the optimizer, not realized P&L. The GP optimizes predictions of predictions.
- **500-candidate GP prediction is fast but shallow.** Matern GP fit on 2–3 points with 500 random candidates is a low-data surrogate — the surface is highly uncertain.
- **Hospital cadence vs Pituitary cadence are unsynchronized.** Hospital might produce a new Platinum at MINT 3, but Pituitary won't run GP until MINT 4. If both fire in the same cycle, Platinum written at MINT 3 is immediately available — otherwise it waits a full GP cycle.
- **Bronze history caps at 10 in vault, 100 in file** — minimal genealogy for debugging parameter drift.

---

## Deep Investigation Findings

### Finding 1: Pituitary GP Data Starvation — Single-Point Training Is Frequent

Silver is the secondary GP training tier. After every GP coronation:
```python
vault["silver"] = None   # consumed
```

Silver is replenished by **ParamCrawler MINE**, which runs every `crawler_mine_interval × 300s` (default `12 × 300 = 3600s ≈ 60 minutes`).

Pituitary GP runs every **4th MINT ≈ 20 minutes** in live operation.

**The cadence mismatch:** GP fires 3× per MINE cycle:
- MINT 4: GP consumes Silver → Silver = None
- MINT 8: GP runs with only Gold (+ Platinum if present)
- MINT 12: MINE may have refilled Silver

In the worst case (no Platinum, Silver consumed): Matern GP trains on **one data point**. A 1-point GP in 23-D space is governed entirely by the kernel prior — the posterior is near-flat. The argmax over 500 random candidates on a near-flat surface is effectively random selection. The coronation proceeds, installs a near-random mutant as Gold, and triggers a full lobe reload.

This is not an edge case. In normal live operation it happens every 2nd and 3rd GP run.

---

### Finding 2: Inline VolumeFurnace vs Batch Hospital — Two Code Paths, One Broken

Two separate optimizer instances share the Stage A-H names but have different vault wiring:

| | **Batch Hospital** | **Inline VolumeFurnace** |
|---|---|---|
| File | `Hospital/Optimizer_loop/service.py` | `volume_furnace_orchestrator/service.py` |
| Runs | Manually / overnight | Every 3rd MINT, live thread |
| Stage H result | `Pituitary.secrete_platinum()` called | Audit table write only |
| Vault effect | Platinum updated → feeds GP | None |

The "Full Optimization Flow" diagram above (`Hospital → secrete_platinum()`) describes the **batch Hospital only**. The inline VolumeFurnace — the one that runs continuously — never calls `secrete_platinum()`. The only optimizer that contributes to parameter evolution is the one that is not running during live trading.
