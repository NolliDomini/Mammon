# Deep Dive: Database Layout — The Runtime Tape

## 1. Overview

Mammon uses **ten distinct storage locations** across five transport types. Six of the ten are either empty in production, never created at normal boot, or pointed at wrong paths. The actual "tape" of a live session is recorded in three active stores; the rest are stubs or migration targets.

```
Redis                     ← Live BrainFrame state + hormonal vault
  mammon:brain_frame:*       (per-pulse, wiped on restart)
  mammon:hormonal_vault      (Gold/Silver/Platinum params)

Hippocampus/Archivist/Ecosystem_Synapse.db (SQLite)
  synapse_mint               ← PRIMARY TRAINING STORE (288 rows/day)

Hippocampus/data/ecosystem_synapse.duckdb (DuckDB)
  optimizer_stage_audit      ← Optimizer audit trail (active)
  opt_stage_runs             ← Stage scaffolding audit (active)
  opt_scores_components      ← Score decomposition (active)
  opt_promotion_decisions    ← Promotion gate decisions (active)
  synapse_mint               ← EMPTY (TheBrain migration target)
  walk_mint / monte_mint     ← EMPTY (TheBrain migration target)

Hippocampus/data/ecosystem_params.duckdb (DuckDB)
  param_sets                 ← Param lineage on every coronation (active)

runtime/.tmp_test_local/compat_librarian.db (SQLite — HIDDEN)
  money_orders               ← ACTUAL MONEY TAPE (TreasuryGland)
  money_fills / positions    ← ACTUAL P&L (TreasuryGland)
  council_mint               ← Short-term Council memory
  turtle_monte_mint          ← Short-term Monte Carlo memory

--- EMPTY OR BATCH-ONLY ---
Hippocampus/Archivist/Ecosystem_Memory.db   ← EMPTY (never written)
Hippocampus/Archivist/Ecosystem_Optimizer.db← EMPTY (never written)
Hospital/Memory_care/duck.db                ← FORNIX BATCH ONLY
Hippocampus/data/Ecosystem_UI.db            ← EMPTY (not created at boot)
Hospital/Memory_care/control_logs.db        ← EMPTY (not created at boot)
```

---

## 2. Storage Location Reference

### 2A. Redis — Live BrainFrame + Hormonal Vault

| Key Pattern | Content | Written By | Read By | Persistence |
|---|---|---|---|---|
| `mammon:hormonal_vault` | HSET of Gold/Silver/Platinum/Bronze tier JSON blobs | `librarian.set_hormonal_vault()` on every vault update | `librarian.get_hormonal_vault()` on engine init + every optimizer cycle | AOF/RDB to `mammon-redis-data` volume |
| `mammon:brain_frame:*` | Per-symbol/pulse BrainFrame state snapshot | WardManager / BrainFrame on every pulse | Cross-lobe reads within a pulse | In-memory; wiped on every engine start by `WardManager.janitor_sweep()` |

**Volume at one day of DRY_RUN trading one symbol (BTC/USD):**
- brain_frame keys: overwritten 864 times (3 pulses × 288 pulses/day); net 1 key per symbol active at end
- hormonal_vault: rewritten on every optimizer coronation (~1–5/day typical)

**Warning:** `WardManager.janitor_sweep()` runs `redis.keys("mammon:brain_frame:*")` — O(N) full keyspace scan. On restart, it deletes every matching brain frame in Redis regardless of namespace. Two Mammon instances sharing a Redis instance would wipe each other's frames on start.

---

### 2B. `Hippocampus/hormonal_vault.json`

| Property | Value |
|---|---|
| Type | JSON file |
| Path | `Hippocampus/hormonal_vault.json` |
| Created | Ships with repo (must exist for non-zero Gold) |
| Written | Mirror-synced by `set_hormonal_vault()` on every vault update |
| Read | Cold-start bootstrap only — if `mammon:hormonal_vault` key absent from Redis |
| Structure | `{gold, silver: [...], platinum, titanium, bronze_history, diamond_rails, meta}` |

**Critical:** If this file has `"params": {}` for Gold (empty params), all lobes start with `gear=0`, producing `tier1_signal=0` every pulse. The system runs but never trades — silently.

---

### 2C. `Hippocampus/Archivist/Ecosystem_Synapse.db` — PRIMARY ML TRAINING STORE

**Type:** SQLite  
**Created by:** SynapseScribe (creates file via `sqlite3.connect()` if absent; does NOT require boot.py)  
**Also routed here:** Telepathy's ScribeDaemon routes SQL containing `synapse_mint` or `history_synapse` to this path — but the Telepathy commit path is broken (`Librarian.get_connection()` static method does not exist → AttributeError on every commit attempt). Effective write path is SynapseScribe direct-only.

#### Table: `synapse_mint`

| Property | Detail |
|---|---|
| Schema | 20 fixed columns + dynamic ALTER TABLE to add new columns per first write of each field. `PRAGMA table_info` called on every write. |
| Fixed cols | `machine_code` (PK), `ts`, `symbol`, `pulse_type`, `execution_mode`, `open/high/low/close/volume`, `price`, `active_hi/lo`, `gear`, `tier1_signal`, `mu`, `sigma`, `p_jump`, `monte_score`, `tier_score`, `regime_id`, `decision`, `approved`, ... |
| Dynamic cols | Any BrainFrame field written via Amygdala `_ensure_columns()` — added on first occurrence. In practice the schema expands to 80+ columns within the first few pulses. |
| Write cadence | Every MINT pulse. ~288 rows/day for 5-minute bars. |
| Written by | `Amygdala → SynapseScribe.write()` via `sqlite3.connect()` |
| Read by | `DiamondGland`, `ParamCrawler`, `SynapseRefinery` (primary training data source for the entire optimizer stack) |
| Retention | 90 days — Pineal `secrete_melatonin()` runs `DELETE WHERE ts < now - 2160h` every MINT |
| First-run state | Empty; DiamondGland / SynapseRefinery have no training data until MINT rows accumulate |

**Note:** The `machine_code` primary key means each row is an upsert (INSERT OR REPLACE). If two MINT pulses share the same machine_code (possible in DRY_RUN where machine_code = run_id + symbol + pulse_count), the newer row overwrites the older one.

#### Table: `history_synapse`

| Property | Detail |
|---|---|
| Purpose | Fornix batch replay staging area |
| Write cadence | Batch path only; written by Fornix replay runs |
| Read by | DiamondGland (consumes staging after Fornix completes) |
| Cleared by | Pineal `finalize_fornix_staging()` after Diamond consumes — **no transaction wrapping, silent data loss risk if INSERT fails** |
| Live run state | Empty |

---

### 2D. `Hippocampus/data/ecosystem_synapse.duckdb` — PARTIALLY ACTIVE

**Type:** DuckDB  
**Created:** At Python import time by `MultiTransportLibrarian.__init__()` via `_setup_mint_tables()`  
**Write path:** `librarian.write_direct(sql, transport="duckdb")` → `get_duck_connection().execute()`

#### Tables and their actual status:

| Table | Schema | Written In Production? | Notes |
|---|---|---|---|
| `synapse_mint` | 96+ columns (all BrainFrame fields + all 47 PARAM_KEYS) | **NO** | `librarian.mint_synapse()` is never called by production code (only `*-TheBrain.py` migration files). SynapseScribe writes to the SQLite counterpart instead. |
| `walk_mint` | 9 cols: ts, symbol, regime_id, mu, sigma, p_jump, confidence, mode, pulse_type | **NO** | `librarian.mint_walk()` only called in `walk/service-TheBrain.py`. |
| `monte_mint` | 12 cols: ts, symbol, pulse_type, paths, price, atr, stop, scores | **NO** | `librarian.mint_monte()` only called in `turtle/service-TheBrain.py`. |
| `optimizer_mint` | 7 cols: ts, symbol, regime_id, fitness, params_json, source, mode | **NO** | `librarian.mint_optimizer()` never called in production. |
| `optimizer_stage_audit` | run_id, ts, stage_name, status, regime_id, metrics_json, reason_code | **YES** | Written by `GuardrailedOptimizer.log_stage_start/end()` via `OptimizerLibrarian` (= `MultiTransportLibrarian`) on every optimizer run. |
| `opt_stage_runs` | Same as optimizer_stage_audit + INTEGER id | **YES** | Duplicate of optimizer_stage_audit; written simultaneously by `log_stage_run()`. |
| `opt_scores_components` | run_id, candidate_id, 7 score component columns | **YES** | Written by `GuardrailedOptimizer.write_score_components()` — one row per evaluated candidate. |
| `opt_diversity_metrics` | run_id, stage_name, entropy, coverage, min_distance | **YES** | Written by `GuardrailedOptimizer.write_diversity_metric()`. |
| `opt_regime_coverage` | run_id, regime_id, candidate_count, support_count | **YES** | Written by `GuardrailedOptimizer.write_regime_coverage()`. |
| `opt_promotion_decisions` | run_id, candidate_id, decision, reason_code, score, ... | **YES** | Written by `GuardrailedOptimizer.write_promotion_decision()`. |
| `optimizer_candidate_library` | candidate_id (PK), run_id, ts, stage, param_json, regime_id, ... | **YES** | Upserted by `GuardrailedOptimizer.upsert_candidate_library()`. |

**Volume estimate:** Each inline VolumeFurnace run (every 3rd MINT) generates ~5–20 rows across optimizer audit tables. Roughly 100–500 rows/day.

---

### 2E. `Hippocampus/data/ecosystem_params.duckdb` — PARAM LINEAGE

**Type:** DuckDB  
**Created:** At Python import time by `MultiTransportLibrarian._setup_param_tables()`

#### Table: `param_sets`

| Column | Purpose |
|---|---|
| `id` | Unique param set ID (e.g., `gold_1717000000`) |
| `tier` | GOLD / SILVER / PLATINUM / BRONZE |
| `params_json` | Full param dict as JSON string |
| `regime_id` | Regime context at coronation |
| `fitness` | Fitness score at time of recording |
| `active_from` | Timestamp this set became active |
| `active_to` | Timestamp this set was retired (NULL = still active) |
| `origin` | Source: "hospital", "inline", "bootstrap" |

| Property | Detail |
|---|---|
| Written by | `librarian.record_new_gold()`, `record_silver_candidate()`, `demote_to_bronze()` |
| Read by | `librarian.get_param_history()` (primarily for diagnostics/inspection) |
| Write cadence | On every optimizer event: Gold coronation, Silver promotion, Bronze demotion |
| First-run state | Empty |
| Fallback | If `ecosystem_params.duckdb` is locked, creates a volatile `runtime/.tmp_test_local/ecosystem_params_{uuid}.duckdb` instead — lineage permanently lost for that session |

---

### 2F. `runtime/.tmp_test_local/compat_librarian.db` — THE HIDDEN MONEY TAPE

**Type:** SQLite  
**Created by:** Any call to `Librarian()` with no path argument → defaults to `Path.cwd() / "runtime" / ".tmp_test_local" / "compat_librarian.db"`  
**Persists:** Yes — inside Docker volume mount (`.:/mammon`), survives container restarts  
**Monitored by SchemaGuard:** No

This file is the actual ledger for all money, P&L, and short-term analytical data. It is written by **TreasuryGland, Council, TurtleMonte, Callosum, and Gatekeeper** — all of which instantiate `Librarian()` directly instead of using the `MultiTransportLibrarian` singleton.

#### Tables (created by TreasuryGland `_init_schema()`):

| Table | Content | Written By | Written When |
|---|---|---|---|
| `money_orders` | One row per trade intent: intent_id (PK), ts, symbol, side, qty, status (ARMED→FILLED/CANCELED/REJECTED/TIMEOUT), price_ref, risk metrics | TreasuryGland `record_intent()` | On every ACTION pulse that fires a trade |
| `money_fills` | One row per fill: fill_id (PK), intent_id FK, fill_price (slippage-adjusted), slippage_bps, fee | TreasuryGland `fire_intent()` | On every MINT pulse that executes an intent |
| `money_positions` | Current position per (symbol, mode): qty, avg_price, unrealized_pnl, realized_pnl | TreasuryGland `_apply_fill_to_position()` | On every fill |
| `money_pnl_snapshots` | Cumulative PnL snapshot per fill: gross_pnl, slippage_impact, fee_impact, net_pnl | TreasuryGland `_snapshot_pnl()` | On every fill event |
| `money_audit` | Event log: ARMED, MINT_FIRED, CANCELED, REJECTED, TIMEOUT, PARTIAL_FILL, PAPER_RECONCILE | TreasuryGland `_audit()` | On every intent lifecycle transition |

#### Tables (created by production lobes via Librarian() shim):

| Table | Created By | Purpose |
|---|---|---|
| `council_mint` | Council | Per-pulse Council confidence/indicator output. Retention: 6h (Pineal) |
| `turtle_monte_mint` | TurtleMonte | Per-pulse Monte Carlo simulation output. Retention: 1h (Pineal) |
| `quantized_walk_mint` | QuantizedWalk (possibly) | Walk trajectory priors. Retention: 6h (Pineal) |
| `callosum_mint` | Callosum | Blended conviction scores |
| `walk_mutations`, `monte_candidates`, `lhs_candidates`, `bayesian_candidates` | Hospital optimizer | Intermediate optimizer candidate pools. Retention: 1h (Pineal) |

**Critical:** Pineal's `secrete_melatonin()` runs `DELETE FROM council_mint WHERE ts < now - 6h` against `Ecosystem_Memory.db` — which is empty. The actual `council_mint` table in `compat_librarian.db` is NEVER pruned. These tables grow unbounded for the lifetime of the container.

---

### 2G. `Hospital/Memory_care/duck.db` — FORNIX BATCH ONLY

**Type:** DuckDB  
**Created by:** `SchemaGuard.ensure_schema_versions()` in `boot.py`, OR Fornix's first run  
**Created at normal boot:** NO — `Start_Mammon.bat` does not call `boot.py`  
**Status at first live run:** Does not exist (Fornix batch will fail with directory-not-found or schema error)

| Table | Content | Written By | Read By |
|---|---|---|---|
| `market_tape` | Historical OHLCV bars (DuckPond data lake) | DuckPond hydrate scripts | Fornix replay engine (SmartGland) |
| `history_synapse` | Fornix replay synapse staging | Fornix replay loop | DiamondGland (after Fornix completes) |
| `fornix_checkpoint` | Resume state for long replay runs | Fornix checkpoint logic | Fornix on restart |

---

### 2H. `Hippocampus/Archivist/Ecosystem_Memory.db` — PERMANENTLY EMPTY

**Type:** SQLite  
**Created by:** `SchemaGuard.ensure_schema_versions()` in `boot.py` only  
**Created at normal boot:** NO  
**Expected tables (per SchemaGuard):** `money_orders`, `money_fills`, `money_positions`, `money_pnl_snapshots`  
**Actual content:** Empty — these tables are created in `compat_librarian.db` by TreasuryGland instead

The Telepathy ScribeDaemon routes non-synapse SQL writes here, but:
1. `librarian.write()` raises TypeError calling `Telepathy().transmit(sql, params, transport=transport)` (transmit() takes only 2 args) → always falls to `write_direct()` → bypasses Telepathy entirely
2. Telepathy's `_commit_batch()` calls `Librarian.get_connection(db_path)` — a static method that does not exist on the `Librarian` class → AttributeError on every commit attempt
3. Both the sender (TypeError) and receiver (AttributeError) are broken in complementary ways — Telepathy's queue is never populated by production code AND would fail to commit if it were

**Consequence:** Pineal prunes `council_mint`, `turtle_monte_mint`, `quantized_walk_mint` from this file — but these tables don't exist here. Pruning is a no-op. The actual tables in `compat_librarian.db` accumulate forever.

---

### 2I. `Hippocampus/Archivist/Ecosystem_Optimizer.db` — PERMANENTLY EMPTY

**Type:** SQLite  
**Created by:** `SchemaGuard.ensure_schema_versions()` in `boot.py` only  
**Expected tables:** `walk_mutations`, `monte_candidates`, `lhs_candidates`, `bayesian_candidates`  
**Actual content:** Empty — intermediate optimizer tables land in `compat_librarian.db` via `Librarian()` shim  
**Pineal pruning target:** Yes — pruning runs against this file and finds nothing

---

### 2J. `Hippocampus/data/Ecosystem_UI.db` — NOT CREATED AT BOOT

**Type:** SQLite  
**Created by:** `SchemaGuard.ensure_schema_versions()` in `boot.py` only  
**Expected tables:** `ui_control_audit`, `ui_projection_deadletter`, `ui_orders`  
**Status:** File does not exist after a normal boot sequence

---

### 2K. `Hospital/Memory_care/control_logs.db` — NOT CREATED AT BOOT

**Type:** SQLite  
**Created by:** `SchemaGuard.ensure_schema_versions()` in `boot.py` only  
**Expected tables:** `librarian_write_log`, `librarian_read_log`  
**Status:** File and directory do not exist after a normal boot sequence  
**Pineal pruning target:** Yes — pruning fails silently if file absent (`_prune_vault()` guards with try/except)

---

## 3. The Runtime Tape — What a Live Session Looks Like

For a single-symbol DRY_RUN session trading BTC/USD on 5-minute bars:

### T+0 to T+5 min (before first pulse)
| Store | State |
|---|---|
| Redis `brain_frame` | Wiped by WardManager on engine start; all zero BrainFrame for duration of wait |
| Redis `hormonal_vault` | Loaded from `hormonal_vault.json`; Gold params cached |
| `Ecosystem_Synapse.db` | Empty (or prior session data) |
| `compat_librarian.db` | Empty (new session) or prior fills |

### Each SEED pulse (3 per 5 min bar = 1728/day)
| Action | Store |
|---|---|
| BrainFrame updated with latest OHLCV bar | Redis |
| Council calculates confidence, writes to `council_mint` | `compat_librarian.db` |
| SpreadEngine updates `frame.environment.spread_*` | Redis |

### Each ACTION pulse
| Action | Store |
|---|---|
| TurtleMonte runs simulation, writes to `turtle_monte_mint` | `compat_librarian.db` |
| SnappingTurtle runs Donchian breakout check | Redis (frame update only) |
| Callosum blends signals, writes to `callosum_mint` | `compat_librarian.db` |
| Gatekeeper approves/blocks trade | Redis |
| If trade: TreasuryGland `record_intent()` → `money_orders` (ARMED) | `compat_librarian.db` |

### Each MINT pulse (~288/day for 5-min bars)
| Action | Store |
|---|---|
| Amygdala `mint_synapse_ticket()` | `Ecosystem_Synapse.db` synapse_mint |
| TreasuryGland: fire, cancel, or timeout pending intents | `compat_librarian.db` money_orders, money_fills, money_positions, money_pnl_snapshots |
| Pineal `secrete_melatonin()` | Prunes `Ecosystem_Synapse.db` (synapse_mint > 90 days); prunes target files `Ecosystem_Memory.db` + `Ecosystem_Optimizer.db` (both empty — no-op) |
| Every 3rd MINT — VolumeFurnaceOrchestrator inline optimizer | `ecosystem_synapse.duckdb` (optimizer audit tables) |
| `pulse_log.append()` in Soul orchestrator | In-memory Python list (never written to disk; grows unbounded at 864 entries/day) |

### End-of-day summary
| Store | Net state |
|---|---|
| `Ecosystem_Synapse.db` synapse_mint | ~288 new rows |
| `compat_librarian.db` money_orders | N rows (N = number of trade intents fired, any status) |
| `compat_librarian.db` money_pnl_snapshots | N rows (one per fill event) |
| `compat_librarian.db` council_mint | ~1728 rows (never pruned) |
| `compat_librarian.db` turtle_monte_mint | ~576 rows (never pruned) |
| `ecosystem_synapse.duckdb` optimizer tables | ~300–1500 rows across audit tables |
| `ecosystem_params.duckdb` param_sets | N rows (N = number of optimizer events) |
| Redis hormonal_vault | Updated if optimizer crowned a new Gold |
| `hormonal_vault.json` | Mirror of current vault |

---

## 4. DB-Level Gaps Summary

| Gap | Description | Impact |
|---|---|---|
| TreasuryGland hidden path | Money tables in `runtime/.tmp_test_local/compat_librarian.db`, not in `Ecosystem_Memory.db` | P&L data in non-obvious path; not backed up with other DBs; not monitored by SchemaGuard |
| Ecosystem_Memory.db permanently empty | Expected tables are in compat_librarian.db; SchemaGuard's money table expectations are never satisfied | Schema checks always show drift for money tables |
| Telepathy double-broken | Sender raises TypeError (extra `transport` kwarg); receiver raises AttributeError (`Librarian.get_connection` doesn't exist). Queue always empty, commits always fail. | Telepathy is a functional no-op; async write bus provides no value |
| Pineal prunes wrong files | Pineal prunes council_mint/turtle_monte from `Ecosystem_Memory.db`; actual data is in compat_librarian.db | Short-term mint tables grow unbounded in compat_librarian.db |
| DuckDB synapse_mint empty | `librarian.mint_synapse()` never called; production synapse data stays in SQLite | Optimizer SQL targeting DuckDB synapse_mint returns empty results; SQLite synapse_mint is the real store |
| Hospital/Memory_care/ not created | `duck.db`, `control_logs.db` not created unless boot.py runs | Fornix batch fails on fresh install |
| Ecosystem_UI.db not created | UI control audit tables missing | Any UI audit write fails silently |

---

## 5. What the Optimizer Actually Reads

Given that several stores are empty, the optimizer training pipeline reads:

| Optimizer | Reads From | What It Gets |
|---|---|---|
| DiamondGland | `Ecosystem_Synapse.db` → synapse_mint (SQLite) | Full BrainFrame history — the real training store |
| ParamCrawler | `Ecosystem_Synapse.db` → synapse_mint (SQLite) | Same — lookback window defined by `crawler_lookback_hours` Gold param |
| SynapseRefinery | `Ecosystem_Synapse.db` → synapse_mint (SQLite) | Regime-segmented synapse history |
| Pituitary GP | Redis `mammon:hormonal_vault` → Silver list | Silver candidates as GP training points |
| GuardrailedOptimizer | `ecosystem_synapse.duckdb` → optimizer audit tables | Stage run history and promotion decisions |
| Hospital Fornix | `Hospital/Memory_care/duck.db` → market_tape | Historical bars (batch only) |

**The optimizer does NOT read:**
- `Ecosystem_Memory.db` (empty)
- `ecosystem_synapse.duckdb` → synapse_mint (empty in production)
- `compat_librarian.db` → any table (money data is fully firewalled from optimizer)
- TimescaleDB (tables never created; only pinged `SELECT 1`)

---

## 6. Fixing the DB Architecture

### Fix 1: Consolidate the money tap
Give TreasuryGland an explicit `db_path` pointing to `Hippocampus/Archivist/Ecosystem_Memory.db` so money tables land where SchemaGuard, Pineal, and backups expect them.

```python
# In _engine_loop, when constructing Trigger:
from Medulla.treasury.gland import TreasuryGland
treasury = TreasuryGland(
    mode=state.mode,
    librarian=Librarian(db_path="Hippocampus/Archivist/Ecosystem_Memory.db")
)
```

### Fix 2: Fix Telepathy.transmit() signature
Add `transport: str = "duckdb"` to `transmit()`, and route to the correct vault based on it (not just SQL text scanning).

```python
def transmit(self, sql: str, params: Any, transport: str = "duckdb"):
    ...
    target = "SYNAPSE" if transport == "synapse" or "synapse_mint" in sql.lower() else "MEMORY"
```

### Fix 3: Add Librarian.get_connection static method
Telepathy's `_commit_batch()` calls `Librarian.get_connection(db_path)` which doesn't exist. Add it:

```python
@staticmethod
def get_connection(db_path):
    import contextlib, sqlite3
    @contextlib.contextmanager
    def _ctx():
        conn = sqlite3.connect(str(db_path), timeout=10.0)
        conn.execute("PRAGMA journal_mode=WAL")
        try:
            yield conn
        finally:
            conn.close()
    return _ctx()
```

### Fix 4: Move short-term mint tables to Ecosystem_Memory.db
Council, TurtleMonte, Callosum, Gatekeeper should use the shared librarian (via `from Hippocampus.Archivist.librarian import librarian`) rather than instantiating `Librarian()`. This places their mint tables in the correct file where Pineal's retention enforcement can reach them.

### Fix 5: Wire boot.py into Start_Mammon.bat
Running `python ../boot.py` before `docker compose up` creates all missing DB files and directories (`Hospital/Memory_care/`, `Ecosystem_UI.db`, `control_logs.db`, `duck.db`) and validates schema before first use.
