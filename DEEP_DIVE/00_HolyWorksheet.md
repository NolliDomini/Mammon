# Holy Worksheet — All Gaps, All Modules

**Compiled from:** 25 deep dive files (01–24 + Capstone).  
**Total gaps identified:** 83  
**Format:** Gap # | One-line statement of the problem | Source doc | Fix path

Priority bands:
- **P1 — System Broken:** system does the wrong thing right now (trades with bad sizing, optimizer learns wrong signal, wrong data shown)
- **P2 — Silent Failure:** something appears to work but outputs are discarded, zeroed, or dead
- **P3 — Infrastructure Risk:** data loss, deadlock, or restart risk under normal operation
- **P4 — Rough Edge:** messy, fragile, or misleading — not immediately dangerous

---

## CATEGORY 1: BOOT & STARTUP

| # | Priority | Gap | Source | Fix |
|---|---|---|---|---|
| B1 | P3 | `boot.py` (`MammonBootstrapper`) is never called by `Start_Mammon.bat`. Schema validation, DB creation (`Hospital/Memory_care/`, `Ecosystem_UI.db`, `control_logs.db`), and TimescaleDB handshake are all skipped. Errors appear silently at first write. | 23_BootSequence | Add `python ../boot.py` to BAT before `docker compose up`, or run it as the dashboard container entrypoint |
| B2 | P3 | TimescaleDB tables (`money_orders`, `trade_intents`, `broadcast_audit`) are never created. `_require_infra()` only pings `SELECT 1`. Any code routing to TimescaleDB gets table-not-found errors silently swallowed. | 23_BootSequence | Add a TimescaleDB migration script to the startup sequence (run from boot.py or Docker entrypoint) |
| B3 | P3 | `Hospital/Memory_care/` directory and `duck.db` are never created by normal boot. Fornix batch will fail on a fresh install with directory-not-found or schema error. | 23_BootSequence, 12_Fornix | Wire `boot.py` — `ensure_schema_versions()` creates this automatically |
| B4 | P1 | If `hormonal_vault.json` has `params: {}` for Gold (empty params on fresh install or misconfigured vault), `active_gear=0` every pulse → `tier1_signal=0` always → no trades ever. System runs silently and appears healthy. | 23_BootSequence, 00_Capstone | `Start_Mammon.bat` / `onboard.py` should verify non-empty Gold entry and seed from a known-good default profile |
| B5 | P2 | DRY_RUN requires Redis + TimescaleDB (same as LIVE). `_require_infra()` hard-fails on either missing infra regardless of mode. There is no offline or local-only mode. | 23_BootSequence, 21_Dashboard | Either add an offline fallback path for DRY_RUN, or make the infra requirement explicit in the UI/onboarding |
| B6 | P4 | Engine start shows "Syncing to 5m boundary — waiting Xs" for up to 5 minutes with no countdown. Brain Frame panels show zeros. User has no indication of progress beyond a static message. | 23_BootSequence, 21_Dashboard | Push SSE countdown tick events every 30s during wait, or add client-side countdown from initial `wait_sec` value |
| B7 | P3 | `SmartGland` state (in-flight window `raw_list`, `context_df`) is in-memory only. A process restart mid-window loses the partial window — that window's MINT never fires. | 01_Thalamus | Persist `raw_list` and `current_window_start` to a small checkpoint file at each bar; restore on startup |
| B8 | P1 | Brain Stem's `pending_entry` and `position` are in-memory only. A process restart while holding an open live trade causes Brain Stem to lose track of the position. On restart, the system does not know it has an open trade and may fire a second entry. | 03_Brain_Stem | Write `pending_entry`/`position` to TreasuryGland on every state change; read on init |

---

## CATEGORY 2: DATA STORAGE & PERSISTENCE

| # | Priority | Gap | Source | Fix |
|---|---|---|---|---|
| D1 | P2 | Telepathy is doubly broken: `librarian.write()` calls `transmit(sql, params, transport=transport)` but `transmit()` only accepts 2 args → TypeError every call → falls to `write_direct()`. Additionally, Telepathy's `_commit_batch()` calls `Librarian.get_connection()` which is a static method that doesn't exist → AttributeError on every commit attempt. The 10,000-item async queue, batch logic, and backoff retry are all operational and receiving zero traffic. | 09_Hippocampus, 16_SynapseScribe, 24_DatabaseLayout | (1) Remove `transport=transport` kwarg from `transmit()` call in `librarian.write()`. (2) Add `@staticmethod get_connection(db_path)` to `Librarian` class |
| D2 | P1 | TreasuryGland instantiates `Librarian()` with no path → SQLite lands at `runtime/.tmp_test_local/compat_librarian.db`. This is the actual money tape (money_orders, fills, positions, PnL, audit). `SchemaGuard` and `Pineal` expect these tables in `Ecosystem_Memory.db`. The two never converge. | 24_DatabaseLayout, 10_Medulla, 21_Dashboard | Pass explicit `db_path="Hippocampus/Archivist/Ecosystem_Memory.db"` to `Librarian()` in TreasuryGland constructor |
| D3 | P3 | Pineal's `secrete_melatonin()` prunes `council_mint`, `turtle_monte_mint`, `quantized_walk_mint` from `Ecosystem_Memory.db` and `Ecosystem_Optimizer.db`. These files are empty. The actual tables are in `compat_librarian.db` (the Librarian shim). Pruning is a no-op. All short-term mint tables grow unbounded in the hidden path. | 24_DatabaseLayout, 14_Pineal | Fix D2 first (move tables to correct file). Then Pineal's existing prune targets will work |
| D4 | P2 | Two `synapse_mint` tables exist (SQLite `Ecosystem_Synapse.db` written by SynapseScribe; DuckDB `ecosystem_synapse.duckdb` never written in production). The DuckDB table has 47+ param columns, execution costs, qty/notional — everything needed for real fitness. The SQLite table has ~20 columns and a proxy fitness metric. Optimizer reads only the SQLite table. | 16_SynapseScribe, 09_Hippocampus | Complete TheBrain migration: switch Amygdala to `librarian.mint_synapse()` and SynapseRefinery to DuckDB transport simultaneously |
| D5 | P3 | Pineal's `finalize_fornix_staging()` runs `INSERT INTO synapse_mint SELECT * FROM history_synapse` then `DELETE FROM history_synapse` with no wrapping transaction. If the INSERT fails partway, DELETE still runs. Entire Fornix replay output is deleted and irrecoverable. | 14_Pineal | Wrap both statements in `BEGIN...COMMIT` with rollback before DELETE |
| D6 | P3 | `history_synapse` in DuckPond has no unique constraint. `write_synapse_batch()` uses plain `INSERT`. Rerunning Fornix without clearing staging duplicates every ticket. Diamond trains on duplicated data, skewing GP surface toward that replay session. | 15_DuckPond | Add `PRIMARY KEY (machine_code)` or `INSERT OR REPLACE` to `write_synapse_batch()` |
| D7 | P3 | DuckPond's DuckDB file (`Hospital/Memory_care/duck.db`) is accessed by Thalamus (live bar writes) and Fornix (batch replay reads/writes). DuckDB has a process-level write lock. Concurrent access deadlocks one process. | 15_DuckPond, 00_Capstone | Use a separate `duck_fornix.db` path for Fornix batch runs, or add a mutex/lock file to block Fornix if live writing is in progress |
| D8 | P3 | DuckDB fallback on lock failure creates a volatile temp file at `runtime/.tmp_test_local/ecosystem_synapse_{uuid}.duckdb`. All optimizer audit writes for that session are lost on restart with no warning beyond a console print. | 09_Hippocampus | Fail hard or queue writes rather than silently switching to a volatile path |
| D9 | P4 | `DuckPond.cortex_precalc` is never auto-refreshed. It runs `DELETE FROM cortex_precalc` + full recompute when `calculate_cortex()` is called manually. Live bars accumulate in `market_tape` continuously but `cortex_precalc` goes stale immediately after the last manual refresh. | 15_DuckPond | Schedule `calculate_cortex()` to run on Fornix completion or on a configurable interval |
| D10 | P4 | DuckPond `run_sunset()` exceptions are silently swallowed. A broken sunset (e.g. disk full, locked DB) stops all retention pruning with no alert. `market_tape` and `market_tape_5m` grow forever (retention is disabled by default). | 15_DuckPond | Emit an MNER code or SSE error event when sunset fails; add a retention default for market_tape |
| D11 | P3 | DuckPond `history_synapse` sunset policy (14-day rolling window) and Pineal's `clear_history_synapse()` both delete from `history_synapse` independently. If sunset fires mid-Fornix replay, in-progress staging tickets are deleted and Fornix loses partial output silently. | 15_DuckPond | Add a Fornix-active flag to DuckPond; sunset skips `history_synapse` while a replay is running |
| D12 | P4 | SynapseScribe runs `PRAGMA table_info` on every `mint()` call (~288/day per symbol) to check for new columns before each write. At scale this adds a round-trip to every commit. | 16_SynapseScribe | Cache the column set in-memory on SynapseScribe instance; invalidate on schema change only |
| D13 | P4 | SynapseScribe's self-extending schema (`_ensure_columns`) never drops phantom columns when BrainFrame fields are renamed. Old columns accumulate, new columns are added, old rows have NULLs. DiamondGland trains on a sparse, drift-contaminated matrix. | 16_SynapseScribe | Version the schema; run a migration to drop obsolete columns on SynapseScribe init |
| D14 | P4 | `ecosystem_params.duckdb` connection silently falls back to a volatile UUID-suffixed temp file if the primary path is locked. Param lineage (Gold/Silver coronation history) is permanently lost for that session. | 24_DatabaseLayout | Fail hard or retry rather than switching to a non-persistent path |
| D15 | P4 | `money_pnl_snapshots` accumulates one row per fill transition with no pruning. `Pineal` does not touch this table (it's in compat_librarian.db, which Pineal can't reach — see D3). Long sessions generate unbounded PnL history. | 10_Medulla, 24_DatabaseLayout | Add retention pruning (e.g., keep last 30 days) once D2 is fixed |

---

## CATEGORY 3: SIGNAL PIPELINE (LIVE PATH)

| # | Priority | Gap | Source | Fix |
|---|---|---|---|---|
| S1 | P1 | Tiers 2–4 of the Right Hemisphere are empty stubs. `MomentumEngine` (MACD), `VelocityEngine` (Bollinger speed), `LevelsEngine` (pivot scanner) are stub classes. The entire system runs on a single Donchian breakout signal with no momentum, velocity, or levels confirmation. | 05_Right_Hemisphere, 00_Capstone | Implement or document as a known architectural limitation; do not let the stubs imply they contribute |
| S2 | P3 | `tier1_signal` is preserved across `reset_pulse()` — it's in `frame.structure` which is not cleared. If Right Hemisphere throws a lobe exception, the previous pulse's `tier1_signal=1` remains active and Soul runs the full ACTION execution path on stale data. | 05_Right_Hemisphere, 04_Soul_Orchestrator | Clear `frame.structure.tier1_signal` in `reset_pulse()`, or add an explicit zero-write in the lobe-error recovery path |
| S3 | P1 | WalkSeed mutation self-reinforcing feedback loop: Walk Silo (DuckDB `walk_mint`) is always empty (see S7). First pulse uses deterministic fallback. Every subsequent pulse reads back its own previous output from `frame.risk.shocks`. The Monte Carlo is scoring survival against noise derived from its own prior output — a closed loop with no market anchor. Shock source `"silo_discharge"` is never reached. | 07_Left_Hemisphere | Fix walk prior write path (see S7); until then, reset to deterministic fallback each pulse rather than recycling mutations |
| S4 | P2 | Monte Carlo lane weights are `[0.15, 0.35, 0.50]` — best-case lane has 50% weight. `monte_score` is structurally optimistic. In volatile regimes, `monte_score` can remain high even when worst-lane survival collapses. | 07_Left_Hemisphere | Expose lane weights as optimizable Gold params (they are in PARAM_KEYS — ensure they're actually reaching TurtleMonte's simulation) |
| S5 | P2 | WalkScribe's `discharge()` reads only the `mu` column from `walk_mint`. `sigma` and `p_jump` written at mint time are ignored when reconstituting the shock distribution. Monte Carlo uses drift values as its shock set — fat-tail behavior from `p_jump` and variance from `sigma` are permanently discarded. | 17_WalkScribe | Extend the `discharge()` SELECT to return `(mu, sigma, p_jump)` as a tuple; update TurtleWalk to use all three |
| S6 | P3 | Walk prior feedback is completely dead. Three compounding failures: (a) `TurtleWalk._mint_seed()` calls `self.librarian.dispatch()` which doesn't exist on `Librarian` → silent `AttributeError`; (b) target table `quantized_walk_mint` has no CREATE TABLE anywhere — only `walk_mint` (DuckDB) exists; (c) even if written to `quantized_walk_mint` (SQLite), WalkScribe reads `walk_mint` (DuckDB). | 17_WalkScribe, 09_Hippocampus | (1) Replace `dispatch()` with `write()` in TurtleWalk. (2) Change INSERT target to `walk_mint`. (3) Change transport to DuckDB. (4) Align schema (add `ts`, `symbol`; remove `jump_mu`, `jump_sigma`, `tail_mult`) |
| S7 | P1 | Council writes `frame.risk.regime_id` (D_A_V_T with Council's bin thresholds). Then `walk_engine.build_seed()` runs next and overwrites with TurtleWalk's D_A_V_T using **different bin thresholds**. TurtleWalk's value is always final on the frame. Council's `regime_weight_table` lookup and TurtleWalk's Walk Silo discharge use different regime dialects. The same market state can produce different regime_id strings from each component. | 06_Council, 07_Left_Hemisphere | Standardize on a single `regime_id` computation function shared by both; or rename TurtleWalk's field to `walk_regime_id` to avoid overwriting Council's value |
| S8 | P2 | SpreadEngine runs before ATR is computed in Council's cycle. Its ATR fallback reads `frame.environment.atr` which is the *previous pulse's* value. On the first pulse after startup, `frame.environment.atr=0.0` (BrainFrame default) → `spread_bps=0` → `spread_score=1.0` (maximum). First pulse confidence is overstated. | 06_Council | Defer SpreadEngine ATR fallback to run after the ATR kernel in the Council cycle; or guard against `atr==0` explicitly |
| S9 | P3 | `pulse_log` in Soul Orchestrator appends one dict per pulse (3 pulses × 288 bars/day = 864/day) with no max-size cap, no pruning, and no API endpoint that reads it. At 30 days this is ~26,000 entries growing in a Python list. | 04_Soul_Orchestrator | Replace `list` with `collections.deque(maxlen=1000)` |
| S10 | P4 | When `tier1_signal=0`, no new Monte Carlo runs, Callosum, or Gatekeeper decisions fire. `frame.risk` is not cleared by `reset_pulse()`. The dashboard Risk panel (`monte_score`, `tier_score`, `regime_id`, survival rates) shows values from the last breakout event — potentially hours old — with no staleness indicator. | 04_Soul_Orchestrator | Zero `frame.risk.monte_score`, `tier_score`, `regime_id` in `reset_pulse()` when `tier1_signal=0`; or add a timestamp field to allow dashboard-side staleness detection |
| S11 | P2 | Callosum dead weights: `callosum_w_adx` and `callosum_w_weak` appear in Gold PARAM_KEYS and are logged to `callosum_mint` with hardcoded `0.5` inputs. They are not used in the blend formula (`raw = monte_score × w_monte + tier1_signal × w_right`). Pituitary GP wastes two optimization dimensions evolving parameters that have no effect. | 08_Corpus_Gatekeeper | Either (a) implement ADX and weakness components in the blend formula, or (b) remove `callosum_w_adx`/`callosum_w_weak` from PARAM_KEYS and the DB log |
| S12 | P4 | `confidence_score` ghost attribute: Gatekeeper writes `frame.command.confidence_score = final_conf`. `CommandSlot` has no such field → dynamic Python attribute with no reader. Duplicate of `final_confidence` (which IS a slot field). Orphaned every ACTION pulse. | 08_Corpus_Gatekeeper | Remove the `frame.command.confidence_score` write, or add `confidence_score` to `CommandSlot` and use it somewhere |
| S13 | P4 | `gatekeeper_min_monte` is applied at two separate gates against two different Monte Carlo simulations (Gatekeeper: 30k-path TurtleMonte output; Brain Stem: own 1k-path prior-biased mini Monte). Same param key, different simulations. A candidate can pass one and fail the other with no logging of the discrepancy. | 08_Corpus_Gatekeeper | Rename Brain Stem's threshold to `brain_stem_min_risk_score` to make the distinction explicit |
| S14 | P1 | Flat trade sizing: `sizing_mult = gatekeeper_sizing_mult = 0.01`. AllocationGland (equity × risk_pct × conviction / stop_distance) is implemented but never called anywhere in the live Soul cycle. Every approved trade fires at exactly 0.01 units regardless of account size, volatility, or conviction. | 03_Brain_Stem, 10_Medulla | Register AllocationGland as a post-Gatekeeper lobe; remove flat `sizing_mult` from Gatekeeper; have AllocationGland write `frame.command.qty` and `sizing_mult` |
| S15 | P2 | Brain Stem's `_run_valuation_gate()` computes `mean`, `sigma`, `upper_band`, `lower_band` (10k-path Monte) and stores them in `pending_entry` only. It does NOT write back to `frame.valuation`. `ValuationSlot` resets to zero every `reset_pulse()`. Dashboard Valuation section (`Mean`, `Z-Dist`) shows `0.00` permanently. | 03_Brain_Stem, 21_Dashboard | After valuation gate completes, write `mean`, `std_dev`, `z_distance`, `upper_band`, `lower_band` to `frame.valuation` |
| S16 | P4 | PonsExecutionCost estimates total cost and writes to `frame.execution`, but: (a) is not registered as a lobe in `_engine_loop`; (b) even when wired, it's informational only — Brain Stem's entry gates do not check `total_cost_bps`. Dashboard Execution section always shows zeros. | 03_Brain_Stem, 21_Dashboard | Register PonsExecutionCost in `_engine_loop`; add a cost gate to Brain Stem's ACTION path (or at minimum stop showing it on dashboard if deliberately informational) |
| S17 | P4 | No short path exists anywhere in Brain Stem or the execution chain. LONG ONLY is an unchecked architectural constraint with no documentation in the system. | 03_Brain_Stem | Document LONG ONLY as an explicit design decision; add a comment or config flag so it's visible |
| S18 | P4 | Brain Stem `_fire_physical()` places an order and does not poll for fill confirmation. No order status check, no fill callback, no partial fill detection at the broker level. | 03_Brain_Stem | Add order status polling after submit; handle partial fills at the broker layer (not just at the TreasuryGland level) |
| S19 | P4 | SELL exits are not pre-recorded as ARMED intents. `_fire_physical("SELL")` is called directly and only the fill is recorded. The intent lifecycle for sells is truncated: no ARMED state, no cancel path, no timeout path — just FILLED or error. | 10_Medulla | Add `record_intent()` call before `_fire_physical("SELL")` to create a sell intent in ARMED state |
| S20 | P4 | Optical Tract has no backpressure. A slow subscriber in `on_data_received()` blocks the entire fan-out. The 50ms soft budget is telemetry-only — never enforced. A slow lobe delays all subsequent lobes and the caller. | 02_Optical_Tract | Enforce the 50ms budget with a per-subscriber timeout; skip (and log) slow subscribers rather than blocking |
| S21 | P4 | Optical Tract does not prevent DataFrame mutation. Any subscriber that modifies the shared df in-place corrupts delivery to all subsequent subscribers silently. | 02_Optical_Tract | Pass `df.copy()` to each subscriber, or add a read-only proxy wrapper |
| S22 | P3 | WardManager's `janitor_sweep()` uses `redis.keys("mammon:brain_frame:*")` — O(N) blocking scan across all Redis keys at every engine boot. On a shared Redis instance this can stall startup by hundreds of milliseconds. | 20_WardManager | Use `redis.scan_iter("mammon:brain_frame:*")` (non-blocking cursor-based scan) instead of `keys()` |
| S23 | P3 | WardManager wildcard delete: `redis.keys("mammon:brain_frame:*")` has no per-instance or per-mode scoping. Two Soul instances sharing a Redis namespace (live + paper) will wipe each other's active BrainFrames on boot. | 20_WardManager | Add per-instance namespace prefix (e.g. `mammon:{instance_id}:brain_frame:*`); WardManager only sweeps its own prefix |

---

## CATEGORY 4: OPTIMIZER & LEARNING LOOP

| # | Priority | Gap | Source | Fix |
|---|---|---|---|---|
| O1 | P1 | Complete P&L firewall: TreasuryGland has real fill data (`money_fills`, `money_positions`, `money_pnl_snapshots`) with actual slippage and fees. Zero optimizer components read it. SynapseRefinery, ParamCrawler, DiamondGland, Pituitary GP, and VolumeFurnace all train on proxy metrics only. The optimization loop is sealed from trading outcomes. | 00_Capstone, 16_SynapseScribe | At minimum: write `realized_pnl` to synapse tickets at MINT (look up fill price vs entry price from TreasuryGland). Use this to replace the placeholder `realized_fitness` formula |
| O2 | P1 | `realized_fitness = (close - active_lo) / (active_hi - active_lo)` is a price-channel position proxy, not P&L. The code explicitly comments: *"This is a placeholder; real fitness will correlate to P/L of the trade if approved."* DiamondGland safety rails and ParamCrawler Silver mining both derive from this signal. A parameter set that maximizes breakout signal rate (firing constantly, losing money) scores highest. | 16_SynapseScribe, 13_DiamondGland | Replace with `realized_pnl / notional` from TreasuryGland (fix O1 first); or at minimum use a multi-factor proxy incorporating execution cost |
| O3 | P1 | Optimizer fitness is structurally circular: `realized_fitness` is high when `close > active_hi` (top of channel) = `tier1_signal=1`. DiamondGland's safe island (fitness > 0.75) constrains GP toward params that fire more breakout signals. The optimizer steers toward signal frequency, not profitability. | 16_SynapseScribe, 00_Capstone | Fix O2; until then document this explicitly so live vault changes are made with awareness |
| O4 | P1 | Inline VolumeFurnace winners (every 3rd MINT, ~every 15 min) are never written to vault. `VolumeFurnaceOrchestrator` has no `PituitaryGland` reference. Stage H returns `promoted=True` → audit table write only. The only optimizer that runs continuously during live trading produces results that are discarded. | 11_Hospital_Pituitary, 22_VolumeFurnace | Wire a `PituitaryGland` reference into `VolumeFurnaceOrchestrator`; call `pituitary.secrete_platinum(winner_params, fitness)` on Stage H promotion |
| O5 | P1 | Pituitary GP data starvation: Silver is consumed (set to `None`) on every GP run. ParamCrawler MINE refills Silver only once per 60 minutes. GP fires every ~20 minutes. 2 of every 3 GP runs train on 1 data point (Gold only, no Silver, no Platinum). A 1-point Matern GP in 23-D space is near-flat — argmax over 500 random candidates is effectively random. A random param set is coronated as Gold and triggers a full lobe reload. | 11_Hospital_Pituitary | Don't consume Silver on every run — only remove Silver entries that were actually used in the selected Gold. Alternatively, increase GP cadence to match MINE interval |
| O6 | P2 | Brain Stem params missing from PARAM_KEYS — the GP optimizer has zero visibility into Brain Stem's actual behavioral controls: `brain_stem_entry_max_z` (Gate 2 z-cap), `brain_stem_mean_dev_cancel_sigma` (MINT cancel threshold), `brain_stem_stale_price_cancel_bps` (stale price guard), `brain_stem_mean_rev_target_sigma` (mean-reversion exit sigma). All default to `0.0` and are never optimized. | 03_Brain_Stem, 00_Capstone | Add these 4 params to PARAM_KEYS and `bounds.py` MINS/MAXS; remove or repurpose the two dead params (O7) to make room |
| O7 | P2 | Two dead params in PARAM_KEYS: `brain_stem_survival` and `brain_stem_noise` are in the 23-param optimization vector but are never read by `trigger/service.py`. GP wastes two optimization dimensions on parameters with no effect. `brain_stem_noise` is used by VolumeFurnace Stage E as a slippage proxy — creating a meaningless penalty. | 03_Brain_Stem, 22_VolumeFurnace | Remove both from PARAM_KEYS and bounds; replace with the 4 real Brain Stem behavioral params (O6) |
| O8 | P2 | ParamCrawler MINE replay kernel only re-synthesizes 2 of 23 params (Callosum blend weights: `callosum_w_monte`, `callosum_w_right`). The other 21 params — Brain Stem weights, Gatekeeper thresholds, Council weights — are not replayed. Silver candidates are scored on a fraction of their actual behavioral signature. | 19_ParamCrawler | Extend `_re_synthesize_tier_score()` to replay Council confidence using Council weight params from the candidate vector |
| O9 | P2 | `realized_pnl` is absent from synapse tickets. ParamCrawler's fitness kernel includes `1 + tanh(realized_pnl)` but always defaults to `ones` (making it equivalent to mean tier_score). The P&L grounding is aspirational dead code. | 19_ParamCrawler | Fix O1 (write realized_pnl to synapse tickets); once present in tickets, the existing kernel will automatically use it |
| O10 | P2 | VolumeFurnace Stage A `_approx_score` pre-filter sees only 4 of 23 params (Monte lane weights + Council ATR/VWAP balance). 19 params are invisible to the fast filter. The candidate population reaching Stages E–H is already biased toward high neutral/best Monte weights and balanced Council weights, regardless of the other 19 dimensions. | 22_VolumeFurnace | Either expand the `_approx_score` filter to include more dimensions, or remove the pre-filter and let Stage E do all the scoring |
| O11 | P3 | Titanium soak uses `frame.risk.monte_score` (live market difficulty signal) as the soak evaluation proxy — not Titanium's own predicted fitness. A strong bull run inflates Titanium's soak scores regardless of whether Titanium's params are responsible. A sideways market will doom any Titanium candidate even if its params are excellent. | 19_ParamCrawler | Replay Titanium's params against the last N synapse tickets (same method as MINE) to compute its soak fitness, rather than using live monte_score |
| O12 | P3 | Gold params control crawler behavior (`crawler_mine_interval`, `soak_window`, `promotion_delta`). A bad GP mutation that changes these values can disable MINE (very long interval) or prevent Titanium soak from ever passing (very high delta). A poor Gold can cripple its own replacement mechanism. | 19_ParamCrawler | Move crawler behavior params to a separate `system_config` section of the vault that is not touched by GP mutation |
| O13 | P3 | DiamondGland trains on only the last 24 hours of synapse history. Intraday regime shifts dominate. A bad overnight session (e.g. post-Fed announcement volatility) can produce rails so tight they block all parameter exploration. | 13_DiamondGland | Make the training window configurable (`diamond_lookback_hours` Gold param); consider using a time-weighted window that emphasizes recent but doesn't discard older regimes |
| O14 | P3 | DiamondGland writes `hormonal_vault.json` directly and synchronously while Soul's `_check_vault_mutation()` may be reading it via Redis bootstrap. No locking on the JSON file. Concurrent writes and reads can produce a corrupted or partially-written vault. | 13_DiamondGland, 00_Capstone | Write to a temp file then `os.rename()` for atomic replacement; or route DiamondGland vault writes through `librarian.set_hormonal_vault()` which uses Redis atomically |
| O15 | P4 | DiamondGland falls back to 90th-percentile if no candidates score > 0.75. Rails are always written even on a flat fitness surface. Tight rails from a flat surface restrict GP exploration unnecessarily; wide rails from a genuinely flat surface provide no value. | 13_DiamondGland | Add a minimum spread threshold: if rails are narrower than X% of the absolute bounds, widen them to prevent over-restriction |
| O16 | P4 | Silver contamination: ParamCrawler MINE runs every ~60 minutes and may re-populate Silver with the same top-50 historical param sets if market conditions haven't changed. Pituitary GP trains on a redundant dataset — a degenerate case of single-point starvation at the population level. | 19_ParamCrawler | Deduplicate Silver candidates by param vector hash before recording; evict exact duplicates |
| O17 | P4 | Fornix's 50-ticket threshold for triggering DiamondGland is hard-coded. A symbol with 40 MINT pulses in its history will never produce safety rails even if it contributes to a larger multi-symbol pool that exceeds 50. | 12_Fornix | Pass the total pool count to `DiamondGland.perform_deep_search()` instead of per-symbol count; or make the threshold configurable |
| O18 | P4 | VolumeFurnace runs on the same thread as the live pulse loop. No timeout on `engine.run_pipeline()`. A slow Bayesian stage (Stage G, every 4th activation) could delay the next SEED→ACTION→MINT sequence past the 5-minute boundary. | 22_VolumeFurnace | Add a timeout to `run_pipeline()` (e.g., 60s); move VolumeFurnace to its own thread with a result queue |

---

## CATEGORY 5: DASHBOARD & UI

| # | Priority | Gap | Source | Fix |
|---|---|---|---|---|
| U1 | P1 | All 6 fields in the Left Nexus financial tray are broken. Frontend reads `d.orders` (gets dict object → `[object Object]`), `d.fills` (missing → 0), `d.positions` (wrong key), `d.net_pnl` (wrong key). When TreasuryGland throws, the error fallback accidentally has the right key names with zeros — so the error path looks correct and the success path looks broken. | 21_Dashboard | Flatten the API response in `api_treasury_status()`: map `open_positions → positions`, flatten orders dict to fired count, sum pnl fields → net_pnl |
| U2 | P2 | Valuation section (`Mean`, `Z-Dist`) permanently shows zeros. Brain Stem computes valuation gate values (10k-path Monte: mean, sigma, upper/lower bands) but stores them in `pending_entry` only. `frame.valuation` is reset to zero every pulse and no lobe writes to it. | 21_Dashboard, 03_Brain_Stem | Fix S15: have Brain Stem write valuation results back to `frame.valuation` |
| U3 | P2 | Execution section (`Slip`, `Cost`) permanently shows zeros. PonsExecutionCost is not registered as a lobe in `_engine_loop`. `frame.execution` resets to zero every pulse. | 21_Dashboard | Fix S16: register PonsExecutionCost |
| U4 | P2 | Command section `Qty`, `Notional`, `Conviction`, `Risk%`, `Size Reason` all permanently show zeros. AllocationGland is never called. Actual trade qty (0.01 units from `sizing_mult`) is not surfaced in any named dashboard field. | 21_Dashboard, 03_Brain_Stem | Fix S14: wire AllocationGland; or at minimum surface `sizing_mult` explicitly in the Command section |
| U5 | P3 | SSE stream uses a single shared `Queue(maxsize=500)` across all browser clients. Events are consumed point-to-point. With two tabs open, each tab receives ~50% of all pulse events. With three tabs, ~33%. Brain Frame panels update at reduced frequency per additional tab. | 21_Dashboard | Maintain a per-client queue list; on each `put()` to the main bus, fan-out to all per-client queues |
| U6 | P4 | Chart is not hydrated on browser reconnect. `hydrateFromCurrentState()` reattaches SSE but does not call `/api/frame/latest`. Chart starts empty on every browser refresh — first candle only appears on the next live pulse. `/api/frame/latest` endpoint exists but is never called from the UI. | 21_Dashboard | Call `/api/frame/latest` in `hydrateFromCurrentState()` to pre-populate the chart and Brain Frame panels |
| U7 | P4 | Gold params strip is loaded once at engine start. Pituitary GP mutation runs every ~20 minutes and installs a new Gold. The strip shows stale params silently — no indicator that Gold has changed. | 21_Dashboard | Subscribe to vault mutation events (or poll `/api/vault/gold` every 30s); refresh strip when Gold ID changes |
| U8 | P4 | `gatekeeper_min_council` is a PARAM_KEYS param with real effect (Council approval gate) but has no cell in the Golden Params strip. | 21_Dashboard | Add a `gatekeeper_min_council` cell to the Strategy group in the strip |
| U9 | P4 | `callosum_w_adx` is in Gold params and logged to `callosum_mint` but missing from the Callosum group in the strip (shows W Monte, W Right, W Weak — omits W ADX). | 21_Dashboard | Add a `callosum_w_adx` cell to the Callosum group |
| U10 | P4 | The entire Brain Stem sub-group (6 params: `brain_stem_w_turtle`, `brain_stem_w_council`, `brain_stem_survival`, `brain_stem_noise`, `brain_stem_sigma`, `brain_stem_bias`) is absent from the Golden Params strip. | 21_Dashboard | Add a Brain Stem group to the strip; note that `brain_stem_survival` and `brain_stem_noise` are dead (see O7) |
| U11 | P4 | Five strip cells (`fee_maker_bps`, `fee_taker_bps`, `max_slippage_bps`, `risk_per_trade_pct`, `equity`) always show `-` because these params are not in Gold PARAM_KEYS. The cells exist but will never populate. | 21_Dashboard | Either add these params to PARAM_KEYS so they appear in Gold, or remove the strip cells |
| U12 | P4 | MNER error codes (`PONS-E-COST-803`, `COUNCIL-E-SPR-701`, etc.) are emitted via `print()` to server stdout. The `mnerLog` div in the dashboard only receives SSE events. Structured diagnostic errors are invisible to the operator in the UI. | 21_Dashboard | Route MNER emissions through the SSE `error` event type in addition to stdout |
| U13 | P4 | Dashboard TradingView chart depends on CDN (`https://unpkg.com/lightweight-charts@4.2.1`). With no internet, the chart section fails completely — no offline fallback, no local copy, no degraded-mode indicator. | 21_Dashboard | Bundle a local copy of Lightweight Charts; or add a graceful fallback that shows a table of recent OHLCV when the chart library fails to load |
| U14 | P4 | Dashboard `/_shutdown` route uses `werkzeug.server.shutdown` which is `None` in production (non-dev WSGI). Falls back to `os._exit(0)` in a background thread — hard kill with no graceful shutdown, no SQLite WAL flush, no queue drain. | 21_Dashboard | Replace with `signal.raise_signal(signal.SIGTERM)` for a clean shutdown sequence |
| U15 | P4 | There are two cells labeled "Spread" in different dashboard sections — one in Environment (`bid_ask_bps`) and one in Valuation (`spread_score`). Different metrics, identical label. | 21_Dashboard | Rename to "Bid/Ask Spread" (Environment) and "Spread Score" (Valuation) |
| U16 | P4 | Wall-clock MINT events fire using stale BrainFrame data from the last bar processed. The dashboard does not distinguish between a fresh-bar MINT and a wall-clock MINT — the user sees the same green pulse dot for both. | 21_Dashboard | Add a `stale_frame` flag to the MINT SSE event; render the pulse dot differently (e.g., amber instead of green) for wall-clock MINTs |

---

## CATEGORY 6: SYSTEM ARCHITECTURE & MIGRATION

| # | Priority | Gap | Source | Fix |
|---|---|---|---|---|
| A1 | P1 | TheBrain migration is half-complete across 40+ files. Read paths (WalkScribe → DuckDB, SynapseRefinery → SQLite) are pointed at different targets than write paths. The current production codebase is coherent only because read/write paths happen to be consistent at the SQLite level — but the DuckDB target architecture is always empty. Switching Amygdala alone to DuckDB without switching SynapseRefinery breaks the optimizer training chain. | 09_Hippocampus, 16_SynapseScribe | Plan and execute the cut-over atomically: Amygdala write to DuckDB + SynapseRefinery read from DuckDB in the same deploy, with a migration of existing SQLite data |
| A2 | P2 | `Librarian` (SQLite test shim, per-instance, no DuckDB) and `MultiTransportLibrarian` (singleton, Redis+DuckDB+TimescaleDB) are two different classes with similar method signatures. Council, TurtleMonte, Callosum, Gatekeeper all instantiate `Librarian()` directly and get per-instance SQLite connections at `compat_librarian.db`. Their analytical writes (council_mint, callosum_mint, etc.) bypass DuckDB entirely. | 09_Hippocampus, 06_Council | Replace `from Hippocampus.Archivist.librarian import Librarian; self.librarian = Librarian()` with `from Hippocampus.Archivist.librarian import librarian` (the module-level singleton) in all production lobes |
| A3 | P4 | `dispatch()` does not exist on either `Librarian` or `MultiTransportLibrarian`. Any lobe calling `self.librarian.dispatch()` gets `AttributeError` silently swallowed. TurtleWalk is the confirmed affected lobe. Any other code calling `dispatch()` is silently dead. | 09_Hippocampus | Either add `dispatch = write` as an alias to both Librarian classes, or find and replace all `dispatch()` calls with `write()` |
| A4 | P4 | Optical Tract `MAX_SUBSCRIBERS=20` caps the name array but not the subscriber list. Subscriber 21+ is added to the list but has no entry in `subscriber_names` — telemetry silently drops their names. | 02_Optical_Tract | Make `MAX_SUBSCRIBERS` a hard cap on the subscriber list as well, or dynamically extend `subscriber_names` |
| A5 | P4 | `run_id` is stored on WalkScribe instance but never used in `discharge()`. The field was likely intended for filtering priors by optimization run. It is dead constructor state. | 17_WalkScribe | Either add `AND run_id = ?` to the discharge query and pass it, or remove the parameter |
| A6 | P4 | DuckDB compat shim (`_install_duckdb_compat_shim`) patches `duckdb.connect` globally at import time to intercept `PRAGMA` and `EXPLAIN QUERY PLAN` calls. This modifies a global and affects all DuckDB connections in the process, including those in unrelated tests or tools. | 09_Hippocampus | Replace the global monkey-patch with a thin connection wrapper class that is used explicitly by the code that needs compatibility |

---

## MASTER SUMMARY

| Category | Total Gaps | P1 | P2 | P3 | P4 |
|---|---|---|---|---|---|
| Boot & Startup | 8 | 2 | 1 | 4 | 1 |
| Data Storage | 15 | 1 | 3 | 7 | 4 |
| Signal Pipeline | 23 | 4 | 5 | 4 | 10 |
| Optimizer & Learning | 18 | 5 | 6 | 4 | 3 |
| Dashboard & UI | 16 | 1 | 3 | 1 | 11 |
| Architecture | 6 | 0 | 1 | 0 | 5 |
| **TOTAL** | **86** | **13** | **19** | **20** | **34** |

---

## P1 ROLLUP — 13 Gaps That Make the System Wrong Right Now

| # | One-Line Statement |
|---|---|
| B4 | Empty vault → gear=0 → no trades, no warning |
| B8 | Position state lost on restart → possible double-entry on live trade |
| D2 | TreasuryGland uses wrong SQLite path → money data invisible to SchemaGuard and Pineal |
| S1 | Tiers 2–4 are stubs → single Donchian breakout is the entire signal |
| S3 | WalkSeed self-reinforcing loop → Monte Carlo runs against its own prior output, not market data |
| S7 | regime_id dialect mismatch → Council and TurtleWalk speak different D_A_V_T languages |
| S14 | Flat sizing (0.01 units) → no risk-based position sizing, AllocationGland dormant |
| O1 | P&L firewall → optimizer never sees trade outcomes |
| O2 | realized_fitness is a proxy (acknowledged placeholder) → optimizer learns wrong signal |
| O3 | Fitness is circular → optimizer maximizes signal rate, not profitability |
| O4 | Inline VolumeFurnace wins discarded → the only optimizer running continuously produces nothing |
| O5 | Pituitary GP data starvation → 2 of 3 GP runs are random 23-D parameter mutations |
| U1 | Financial tray all 6 fields broken → operator can never see orders, fills, or P&L in the UI |

---

## DEPENDENCY ORDER FOR P1 FIXES

```
Fix D2 (TreasuryGland path)
  └── Enables O1 (P&L feedback)
        └── Enables O2 (real realized_fitness)
              └── Resolves O3 (circular optimizer)
                    └── Enables meaningful rails from O13/DiamondGland

Fix S15 (Brain Stem writes frame.valuation)
  └── Resolves U2 (Valuation section shows data)

Fix S14 (wire AllocationGland)
  └── Resolves U4 (Command section shows data)

Fix O4 (wire Pituitary in VolumeFurnace)
  └── Requires O5 fix (data starvation) to be meaningful

Fix S6 (WalkScribe write path)
  └── Resolves S3 (self-reinforcing mutations)
  └── Improves Stage D context for O4 (VolumeFurnace promotions have real shock data)

Complete TheBrain migration (A1)
  └── Makes D4 (two synapse stores) coherent
  └── Unlocks richer optimizer training data
```
