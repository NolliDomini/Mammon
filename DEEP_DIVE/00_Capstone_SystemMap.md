# Mammon System Map — Capstone Overview

## The One-Line Summary
Mammon is a neural-inspired algorithmic trading system where live market data flows through a brain-anatomical pipeline every 5 minutes, producing a binary fire/no-fire decision. In parallel, a genetic optimization loop continuously refines the parameters that govern that decision.

---

## Two Separate Worlds

Everything in Mammon splits cleanly into two worlds that communicate only through the **hormonal vault**:

```
┌─────────────────────────────────────────────────────┐
│  LIVE WORLD  (real-time, every pulse)               │
│  Thalamus → Soul Pipeline → Brain Stem              │
│  Reads: hormonal_vault (Gold params)                │
│  Writes: synapse tickets, walk priors, trade intents│
└──────────────────────┬──────────────────────────────┘
                       │  vault (Redis / JSON)
┌──────────────────────▼──────────────────────────────┐
│  OPTIMIZER WORLD  (batch, scheduled)                │
│  Fornix → DiamondGland → Hospital → Pituitary       │
│  Reads: synapse history, DuckPond bars               │
│  Writes: new Gold params back to vault              │
└─────────────────────────────────────────────────────┘
```

---

## The Live Pulse — End to End

Every 5-minute bar triggers a **Triple-Pulse sequence**: SEED (2.25m) → ACTION (4.5m) → MINT (5m boundary).

```
Market bar arrives
    │
    ▼
[01 Thalamus / SmartGland]
    Resamples 1m → 5m pulses
    Writes raw bars to DuckPond (market_tape)
    │
    ▼
[02 Optical Tract]
    Synchronous fan-out (spray) to all subscribers
    Soft 50ms budget per subscriber
    │
    ▼
[04 Soul Orchestrator]  ←── reads Gold params from Redis vault on ID change
    Owns the BrainFrame (shared mutable state)
    Calls each lobe in sequence per pulse
    │
    ├──► [05 Right Hemisphere — SnappingTurtle]
    │       Donchian breakout detection
    │       Sets tier1_signal = 1 if close > prev_active_hi
    │
    ├──► [06 Council]
    │       5-indicator confidence blend (ADX 60% dominant)
    │       Computes D_A_V_T regime_id
    │       Sets council_score
    │
    ├──► [07 Left Hemisphere — TurtleMonte]
    │       30,000-path Monte Carlo survival simulation
    │       3 noise lanes: worst(2×) / neutral(1×) / best(0.5×)
    │       Weighted [0.15, 0.35, 0.50] → monte_score
    │       WalkScribe feeds regime-keyed historical priors
    │
    ├──► [08 Corpus Callosum]
    │       Blends monte_score + tier1_signal → tier_score
    │       Passthrough at default weights
    │
    ├──► [08 Gatekeeper]
    │       Binary gate at ACTION: approved = 1 if both
    │       monte_score ≥ min_monte AND council_score ≥ min_council
    │
    ├──► [03 Brain Stem — Trigger]
    │       ARM at ACTION (if approved=1 and tier1_signal=1)
    │       FIRE at MINT (if still armed and confidence holds)
    │       Writes BUY intent → TreasuryGland
    │       LONG ONLY. Mean-dev cancel. PonsExecutionCost informational.
    │
    ├──► [Amygdala]          — writes BrainFrame snapshot to SQLite
    ├──► [Pineal]            — MINT: purges stale rows from SQLite vaults
    ├──► [Pituitary]         — every 4th MINT: GP mutation → new Gold
    └──► [ParamCrawler]      — MINT: MINE silver / PROMOTE titanium
```

---

## The Hormone Hierarchy

```
PLATINUM  ← Hospital VolumeFurnace (batch optimizer winner)
   │
GOLD      ← Pituitary GP mutation (every 4th MINT)
   │         ParamCrawler PROMOTE (Titanium soak winner)
   │
SILVER    ← ParamCrawler MINE (top historical replays)
   │         Fed back into Pituitary GP training
   │
TITANIUM  ← Challenger on soak test (set externally / by optimizer)
   │
BRONZE    ← Demoted Gold entries (rolling archive, last 50)
```

Soul always executes with the **best available tier**: Platinum → Gold → Silver → defaults.

---

## The Optimizer Loop — Batch World

```
[DuckPond]  ←── accumulates raw 1m bars from Thalamus (live) or CSV (bulk load)
    │
    ▼
[12 Fornix]  (manual / scheduled overnight)
    Replays DuckPond bars through a full Soul pipeline per symbol
    Mints BrainFrame snapshots → history_synapse (DuckPond)
    │
    ├──► [13 DiamondGland]  (post-replay)
    │       Fits Matern GP on 24h of synapse tickets
    │       Extracts safe_island (predicted fitness > 0.75)
    │       Writes diamond_rails {min,max} bounds → vault
    │       These bounds constrain Pituitary GP mutation
    │
    └──► [14 Pineal]  (post-Diamond)
            Archive history_synapse → brainframe_mint_archive
            Wipe staging only if Diamond consumed it

[11 Hospital / Optimizer_v2]  (separate scheduled run)
    Stage A–H: LHS sampling → Monte scoring → Bayesian exploit
    GuardrailedOptimizer gates each candidate:
        score ≥ 0.50, drawdown ≤ 0.20, stability ≥ 0.55,
        slippage_adj ≥ 0.45, support ≥ 100, drift ≤ 0.25
    Winner → Platinum via Pituitary.secrete_platinum()
```

---

## The Storage Layer

```
Redis (hot, live)
    hormonal_vault    — Gold/Platinum/Silver/Titanium params (source of truth)
    brain_frame:*     — Live BrainFrame snapshots per symbol/mode
    WardManager wipes brain_frame:* on Soul boot

DuckDB (analytical, Hospital/Memory_care/duck.db)
    market_tape       — Raw 1m bars (Thalamus writes, Fornix reads)
    market_tape_5m    — Live 5m aggregates
    cortex_precalc    — Pre-computed ATR/bands/regime tags
    history_synapse   — Fornix replay BrainFrame snapshots (staging)
    brainframe_mint_archive — Long-lived post-Pineal archive
    walk_mint         — TurtleWalk regime-keyed drift priors (WalkScribe reads)
    monte_mint        — Monte Carlo simulation snapshots
    optimizer_*       — GuardrailedOptimizer audit trail

SQLite (operational, Hippocampus/Archivist/)
    Ecosystem_Synapse.db  — Live synapse tickets (SynapseScribe writes)
    memory_db             — turtle_monte_mint, council_mint (short-lived)
    optimizer_db          — Optimizer run history
    control_db            — Control table

TimescaleDB (audit ledger)
    trade_intents     — TreasuryGland order lifecycle

JSON file (fallback)
    hormonal_vault.json  — Redis mirror; used when Redis unavailable
```

---

## Key Invariants

| Invariant | Where enforced |
|---|---|
| ARM at ACTION, FIRE at MINT | Brain Stem Trigger |
| tier1_signal = 1 required to ARM | Soul Orchestrator |
| LONG ONLY | Brain Stem (no short path exists) |
| Gold params normalize weight groups to sum=1 | bounds.py + normalize_weights() |
| GP mutation clamped to diamond_rails | Pituitary._run_gp_mutation() step 7 |
| Mutated params validated against absolute MINS/MAXS | validate_hormonal_integrity() |
| history_synapse wipe only after Diamond consumed | Pineal.finalize_fornix_staging() |
| BrainFrame Redis keys wiped on every Soul boot | WardManager.janitor_sweep() |

---

## Critical Risks (System-Wide)

**1. Fitness signal is a proxy, not P&L.**
`realized_fitness` in SynapseRefinery is `(close - active_lo) / (active_hi - active_lo)` — a price position within the Donchian channel. DiamondGland safety rails and ParamCrawler's replay kernel are both derived from this proxy. No component uses actual trade P&L to evaluate parameter quality.

**2. The Librarian naming confusion.**
`Librarian` (lowercase import, SQLite shim) and `MultiTransportLibrarian` (singleton, Redis+DuckDB+SQLite) are different classes. SynapseRefinery uses the SQLite shim. Wrong class in the wrong place silently bypasses Redis and DuckDB transport.

**3. Race condition: Diamond writes vault directly.**
DiamondGland writes `diamond_rails` to `hormonal_vault.json` synchronously while Soul may be reading it via Redis bootstrap. No locking.

**4. Single DuckDB write lock.**
DuckDB holds a process-level write lock. Concurrent Thalamus (live) + Fornix (batch) writes to the same `duck.db` will deadlock. Running Fornix while live is active is unsafe without a separate DB path.

**5. Incomplete parameter replay.**
ParamCrawler's MINE mode re-synthesizes only the Callosum blend (`callosum_w_monte` + `callosum_w_right`). The other 21 parameters — Brain Stem weights, Council weights, Gatekeeper thresholds — are not replayed. Silver candidates are scored on a fraction of their actual behavior.

**6. Monte Carlo walk priors read only `mu`.**
WalkScribe returns only the drift column from `walk_mint`. Sigma and jump parameters written by TurtleWalk are ignored when reconstituting the shock distribution. Live Monte Carlo may systematically underestimate tail risk.

**7. Walk prior feedback system is completely non-functional.**
Three compounding failures: (a) `TurtleWalk._mint_seed()` calls `self.librarian.dispatch()` — a method that does not exist on `Librarian`, silently raising `AttributeError`; (b) even if the write succeeded, it targets `quantized_walk_mint` (SQLite) while WalkScribe reads `walk_mint` (DuckDB) — different table, different store; (c) `walk_mint` in DuckDB has no write path in production code. `shock_source = "silo_discharge"` is never hit. TurtleMonte always runs on defaults or frame shocks.

**8. Telepathy is bypassed for all DuckDB/TimescaleDB writes.**
`MultiTransportLibrarian.write()` calls `Telepathy().transmit(sql, params, transport=transport)` but `transmit()` accepts only 2 args — the extra `transport` keyword raises `TypeError`, caught silently, falls to `write_direct()`. All analytical writes are synchronous. The async queue is operationally dead for the main data path.

---

## The Migration (service.py → service-TheBrain.py)

Every major module has two versions: `service.py` (production) and `service-TheBrain.py` (target). This is a systematic in-progress refactor. ~40 files carry a TheBrain counterpart.

**What changes in TheBrain:**
- Amygdala writes to DuckDB via `librarian.mint_synapse()` (currently: SQLite via SynapseScribe)
- Walk priors go to DuckDB `walk_mint` via a working write path (currently: dead)
- Pineal purges DuckDB tables directly (currently: SQLite only)
- Telepathy is either fixed or replaced

**Current state implication:**
The optimization loop (DiamondGland, ParamCrawler) reads from SQLite synapse tickets — this is consistent with what Amygdala writes. It works, but the richer DuckDB schema (execution costs, all 47 param columns) is inaccessible. Walk prior feedback does nothing. The system trades correctly; it learns poorly.

**Safe migration path:**
Amygdala write and SynapseRefinery read must both switch to DuckDB simultaneously, or the optimizer loses its training data during the cut-over.

---

## Module Dependency Map

```
Soul Orchestrator
  ├── SmartGland (Thalamus)
  ├── OpticalTract
  ├── BrainFrame
  ├── SnappingTurtle (Right Hemisphere)
  ├── Council + SpreadEngine
  ├── TurtleMonte + TurtleWalk + WalkScribe
  ├── Callosum + Gatekeeper
  ├── Brain Stem + PonsExecutionCost
  ├── Amygdala → SynapseScribe → Ecosystem_Synapse.db
  ├── Pineal → SQLite vaults
  ├── Pituitary → Redis vault → diamond_rails from vault
  ├── ParamCrawler → SynapseRefinery → Ecosystem_Synapse.db
  └── WardManager → Redis (boot only)

Fornix (batch)
  ├── DuckPond (bar source)
  ├── Soul pipeline (per symbol)
  ├── DiamondGland → SynapseRefinery → vault
  └── Pineal (finalize staging)

Hospital (batch)
  ├── DuckPond (bar source)
  ├── GuardrailedOptimizer → OptimizerLibrarian → DuckDB
  └── Pituitary.secrete_platinum() → Redis vault

MultiTransportLibrarian (singleton)
  ├── Redis (vault hot-table)
  ├── DuckDB (analytical tables)
  └── SQLite (operational tables + Telepathy async queue)
```

---

## The Loop, Summarized

```
Live bars → Thalamus → Soul pipeline → BrainFrame snapshots
    ↓ (every MINT)                        ↓ (async)
Brain Stem fires                    SynapseScribe writes tickets
    ↓                                     ↓
TreasuryGland logs intent          Ecosystem_Synapse.db accumulates
    ↓
Overnight: Fornix replays bars → DiamondGland derives rails → vault
    ↓
Pituitary GP (every 4th MINT) reads vault + rails → crowns new Gold
    ↓
Soul hot-reloads Gold on next vault ID change
    ↓
Loop continues with improved parameters
```