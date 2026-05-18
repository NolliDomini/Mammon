[Mammon Alignment Stamp]
Date: 2026-03-01
Status: Mammon strict-pass aligned (contracts 120/120, integration 20/20).

# Leges Mammon (v3.0)
## The Law of the Machine (Execution Friction + Evolution Edition)
Date: 2026-02-28
Status: Active Runtime Law

---

## I. Mission Law (The Purpose)
Mammon is a pulse-driven, multi-transport, cost-aware decision engine.
Its job is to convert raw market data into structured, risk-aware, cost-adjusted intents — sized by mean-reversion conviction — and persist the neural sequence for evolutionary learning.

---

## II. Ownership Law (The Boundaries)
Logic MUST reside within its authoritative lobe. Logic drift is a violation of the Machine's integrity.
- **Thalamus**: Dumb Ingestion/Resampling only. NO intelligence math. OWNS bid/ask passthrough via `get_snapshot()`.
- **Council**: Environmental Intelligence. OWNS all indicator math (ATR, ADX, VWAP, Volume, **Spread**). Spread is the 5th indicator — normalized, never a kill switch.
- **Right Hemisphere**: Structure authority. OWNS breakouts and technical levels.
  - **Tier 1 (Snapping Turtle)**: OWNS breakout detection and active price boundaries (hi/lo).
  - **Tier 2 (Momentum)**: [Stub] Inflection engine for MACD Reversal acceleration.
  - **Tier 3 (Velocity)**: [Stub] Velocity engine for Bollinger Band expansion speed.
  - **Tier 4 (Levels)**: [Stub] Levels engine for Pivots, whole rounds, and daily/weekly levels.
- **Left Hemisphere**: Risk authority. OWNS survival simulations and priors.
- **Corpus**: Synthesis authority. OWNS signal blending and the OpticalTract bus.
- **Medulla**: Policy/Money authority. OWNS the decision and the Ledger. **AllocationGland** OWNS mean-reversion position sizing.
- **Brain Stem**: Execution authority. OWNS order firing, safety valves, **valuation surface** (mean/std_dev/z_distance → BrainFrame), and **Pons execution cost** (TCA estimation).
- **Hippocampus**: Persistence authority. OWNS the data stream, synapse, **Param DB**, and **Crawler** (MINE + PROMOTE modes).
- **Hospital**: Evolutionary authority. OWNS the **5 split domain optimizers** and Platinum discovery within Diamond rails.
- **Pituitary**: Genetic authority. OWNS Platinum promotion, Bronze retirement, integrity validation, **Diamond** (ML pipeline, rails + Titanium synthesis). GP mutation is ARCHIVED.

---

## III. Pulse Law (The Rhythm)
The engine runs strictly on the Triple-Pulse cadence:
- **SEED** (+2.25m): Situational awareness and prior-priming. Spread engine evaluates.
- **ACTION** (+4.5m): Policy authorization, execution arming, **cost estimation (Pons)**, **position sizing (Allocation)**.
- **MINT** (Rollover): Lifecycle finalization, firing with sized qty, state minting, **Crawler maintenance**.

No lobe may act outside its assigned pulse window. Stale pulses (>30s) are illegal.

---

## IV. Persistence Law (The Memory)
- All data interactions MUST use the `MultiTransportLibrarian`.
- **Durable Memory**: Money-state transitions (ARMED/FIRED/REJECTED) must be stored in TimescaleDB.
- **Analytical Memory**: High-volume synapse snapshots (now including cost/valuation/sizing fields) and indicator "mints" belong in DuckDB.
- **Sub-Millisecond Memory**: Live BrainFrame and Hot-Params reside in Redis.
- **Genetic Memory**: Parameter genealogy (every Gold/Silver/Platinum/Titanium/Bronze transition) persists in `Ecosystem_Params.db`.

---

## V. Evolution Law (The DNA)
- No parameter set may be installed as "Gold" without passing the **Safety Gate** (range-checks on all 46 dimensions).
- **GP mutation is ARCHIVED**. Gold only changes through the Titanium → Crawler PROMOTE path.
- **Promotion Chain**: `Optimizer → Platinum → Crawler MINE → Silver → Diamond ML → Titanium → Crawler PROMOTE (soak window) → Gold → Bronze`.
- **Soak Quarantine**: Titanium must outperform Gold by `promotion_delta` over `soak_window` MINTs before promotion.
- **Diversity Floor**: Promotion is denied if the candidate is mathematically too close to the incumbent.
- **Split Optimization**: Five domain-specific optimizers (Risk, Strategy, Council, Synthesis, Execution) run in parallel on the 15-minute cadence, each constrained by Diamond rails.

---

## VI. Execution Friction Law (The Cost)
- **No Blind Trades**: Every ACTION pulse computes expected execution cost (spread + slippage + fees) before sizing.
- **Mean-Reversion Sizing**: Position size is proportional to z_distance (price deviation from mean). Farther below mean → larger position. At/above mean → no trade.
- **Cost Penalty**: Execution cost penalizes sizing conviction. High-friction environments produce smaller positions.
- **Spread is Intelligence**: Spread is the 5th Council indicator. Wide spreads degrade confidence organically — they do not kill trades directly.

---

## VII. Safety Law (The Guard)
- **Credential Guard**: Machine halts if credentials are missing or default.
- **Paper Lockdown**: `paper=True` is the immutable system default.
- **Fail-Closed**: Any lobe failure, schema drift, or timing violation inhibits trade fire.
- **Fail-Closed Sizing**: Allocation failure → `qty = 0`, `ready_to_fire = False`. No silent trades.
- **Conservative Fallbacks**: Missing bid/ask → `bid = close, ask = close`. Pons failure → `total_cost_bps = max_cost_cap_bps`.

---

## VIII. Canon References
- `CONSTITUTION.md` (Version 3.0.0)
- `HANDOFF_EXECUTION_FRICTION_AND_EVOLUTION.md` (v1.0)
- `Brain_Stem_HANDOFF.md`
- `Brain_Stem_OVERVIEW.md`
- `MASTER_MAMMON_CHECKLIST.md` (v4.0, 298 pieces)
- `ARCHITECTURE_OWNERSHIP.md`


