# Mammon Fix Plan
*Last updated: 2026-04-20*

Four phases. Each phase is independently shippable. Later phases depend on earlier ones only where noted. Every task names the exact file(s) to touch.

---

## Phase 0 — Structural Cleanup (no behavioral change)

These are safe to do before anything else. They don't affect runtime behavior.

### 0-A: Purge test artifacts from runtime/
**Delete:**
- `runtime/.tmp_test_local/ecosystem_*.duckdb` + `.wal` (~40 files)
- `runtime/.tmp_test_local/v2_*.db` (~20 files)
- `runtime/.tmp_test_local/ecosystem_params_*.duckdb.wal`

**Keep:** `runtime/.tmp_test_local/compat_librarian.db` — this is the live money tape.

**Then add to `.gitignore`:**
```
runtime/.tmp_test_local/*.duckdb
runtime/.tmp_test_local/*.duckdb.wal
runtime/.tmp_test_local/v2_*.db
Hippocampus/Archivist/snapshots/
```

### 0-B: Orphaned WAL files
**Delete:**
- `Hippocampus/data/Ecosystem_UI.db-shm`
- `Hippocampus/data/Ecosystem_UI.db-wal`
(Main DB doesn't exist; these are leftovers)

### 0-C: Duplicate scripts
`scripts/*.py` and `scripts/tools/*.py` are identical pairs. Keep `scripts/tools/` (proper package). Delete the top-level copies:
- `scripts/check_gaps.py`
- `scripts/fix_data.py`
- `scripts/hydrate_data_lake.py`
- `scripts/rotate_backtest.py`
- `scripts/temp_lab_thalamus.py`
- `scripts/test_alpaca_live.py`
- `scripts/verify_mean_dev_kill.py`

Same for `Hippocampus/utils/*.py` vs `Hippocampus/utils/tools/*.py`:
- Delete `utils/fill_gaps.py`, `utils/stitch_data.py`, `utils/mint_press.py`, `utils/playback_harness.py`, `utils/generate_lurk_breakout.py`

### 0-D: Archived dead code
- Delete `Pituitary/archived/gp_mutation_v3.py` and the `archived/` folder
- Delete `Hippocampus/Archivist/snapshots/*.json` (runtime artifacts)

### 0-E: Consolidate Context/ governance docs
`Hippocampus/Context/` has three overlapping folders: `00_READ_FIRST_CANON/`, `Canon/`, `Governance/`.
- Keep `00_READ_FIRST_CANON/` as the single source
- Merge any unique content from `Canon/` and `Governance/` into it
- Delete `Canon/` and `Governance/`

### 0-F: Consolidate param JSON files
Multiple param JSON copies scattered across repo. The engine reads only `Hippocampus/hormonal_vault.json`.
- Verify `Hippocampus/gold_params.json`, `Hippocampus/silver_params.json` are not imported
- Verify `Pituitary/params/gold_params.json`, `Pituitary/params/platinum_params.json` are not imported
- Delete confirmed orphans; keep `Hippocampus/hormonal_vault.json` as single source

### 0-G: Rename migration requirements
```
requirements-TheBrain.txt → requirements-migration.txt
```

### 0-H: TheBrain migration files — quarantine decision
Every major service has `service-TheBrain.py` alongside `service.py`. These are not imported in production. Two options:

**Option A (recommended):** Move all `*-TheBrain.py` files into a single `_migration/` folder at repo root, preserving their paths in a manifest. Keeps them accessible without polluting the module tree.

**Option B:** Delete them (recoverable from git).

Files to touch: ~40 `*-TheBrain.py` files across Brain_Stem, Cerebellum, Corpus, Hippocampus, Hospital, Left_Hemisphere, Medulla, Pituitary, Right_Hemisphere, Thalamus.

### 0-I: Module-level stub .py files
Before deleting each: `grep -r "from X import"` to confirm nothing imports the stub directly.
Confirmed stubs (all have a proper submodule dir with the same name):
```
Hippocampus/amygdala.py, fornix.py, pineal.py, telepathy.py, duck_pond.py, schema_guard.py
Medulla/gatekeeper.py, orders.py
Cerebellum/council.py, Soul/brain_frame.py, Soul/orchestrator.py
Corpus/callosum.py
Left_Hemisphere/Monte_Carlo/turtle_monte.py
Right_Hemisphere/Snapping_Turtle/engine.py
Hospital/Optimizer_loop/guardrailed_optimizer.py, optimizer_v2.py, volume_furnace_orchestrator.py, bounds.py
Pituitary/gland.py, refinery.py, metabolism_daemon.py, diamond_deep_search.py
Thalamus/relay.py
```

### 0-J: Cerebellum/gatekeeper/ — check if dead
`Cerebellum/gatekeeper/service.py` exists alongside `Medulla/gatekeeper/service.py`. The engine registers only the Medulla one.
- `grep -r "Cerebellum.gatekeeper"` across codebase
- If no hits: delete `Cerebellum/gatekeeper/`

---

## Phase 1 — Fix the Plumbing (P1 Broken Infrastructure)

These tasks make currently-broken things actually work. Do in dependency order.

### 1-A: Wire boot.py into Start_Mammon.bat
**Problem:** `MammonBootstrapper.run_handshake()` does schema validation, DB creation, and TimescaleDB check — it's never called. Schema drift and missing tables go undetected.

**File:** `boot/Start_Mammon.bat`

**Change:** Add after the docker-compose step and before the health poll:
```bat
echo [*] Running schema handshake...
docker compose -f "!ROOT_DIR!\docker-compose.yml" exec -T dashboard python /mammon/boot.py
if %errorlevel% neq 0 (
    echo [!] Schema handshake failed. Check logs.
    pause
    exit /b 1
)
```

**Done when:** `boot.py` runs on every start; missing tables are created before Flask opens.

---

### 1-B: Create TimescaleDB tables on startup
**Problem:** `money_orders`, `trade_intents`, `broadcast_audit` never created. `_run_migrations()` attempts `ALTER TABLE money_orders` which fails silently.

**File:** Create `scripts/migrations/timescale_init.sql`

```sql
CREATE TABLE IF NOT EXISTS money_orders (
    id TEXT PRIMARY KEY,
    run_id TEXT,
    symbol TEXT,
    side TEXT,
    qty NUMERIC,
    order_type TEXT,
    status TEXT,
    transport TEXT DEFAULT 'timescale',
    created_at TIMESTAMPTZ DEFAULT NOW()
);
CREATE TABLE IF NOT EXISTS trade_intents (
    id TEXT PRIMARY KEY,
    run_id TEXT,
    symbol TEXT,
    side TEXT,
    qty NUMERIC,
    created_at TIMESTAMPTZ DEFAULT NOW()
);
CREATE TABLE IF NOT EXISTS broadcast_audit (
    id SERIAL PRIMARY KEY,
    event_type TEXT,
    payload JSONB,
    created_at TIMESTAMPTZ DEFAULT NOW()
);
```

**Also:** Call this from `boot.py`'s `run_schema_smoke_check()` via `psycopg2.connect(...)`.

**Done when:** TimescaleDB contains the tables; `_run_migrations()` ALTER succeeds.

---

### 1-C: Fix TreasuryGland path
**Problem:** `TreasuryGland` instantiates `Librarian()` with no path → hidden `runtime/.tmp_test_local/compat_librarian.db`. Money data is unmonitored and Pineal never prunes it.

**File:** `Medulla/treasury/gland.py`

**Change:** Pass an explicit path:
```python
# Before
self.librarian = librarian or Librarian()

# After
_DEFAULT_MONEY_DB = Path(__file__).parents[3] / "Hippocampus" / "Archivist" / "Ecosystem_Memory.db"
self.librarian = librarian or Librarian(db_path=_DEFAULT_MONEY_DB)
```

**Also update:** `Hippocampus/Archivist/librarian.py` — `Librarian.__init__` currently defaults to cwd-relative path. Make the default `None` and only fall back to the explicit path if nothing else is given, so tests can still pass a temp path.

**Done when:** `money_orders`, `money_fills`, etc. land in `Ecosystem_Memory.db`. Pineal retention starts working. MCP `money_tape()` finds data.

---

### 1-D: Fix Telepathy — transmit() signature
**Problem:** `librarian.write()` calls `Telepathy().transmit(sql, params, transport=transport)` but `transmit()` only accepts 2 args → TypeError every call → always falls to `write_direct()`.

**File:** `Hippocampus/telepathy/service.py`

**Change:** Add `transport` parameter to `transmit()`:
```python
# Before
def transmit(self, sql: str, params: Any):

# After
def transmit(self, sql: str, params: Any, transport: str = "sqlite"):
    self._daemon.enqueue(sql, params, transport=transport)
```

**Also fix `_commit_batch()`:** It calls `Librarian.get_connection(db_path)` which is not a static method.
```python
# Before
conn = Librarian.get_connection(db_path)

# After
conn = sqlite3.connect(db_path)
```

**Done when:** Telepathy queue actually receives and commits writes. Async persistence works.

---

### 1-E: Fix dashboard financial tray (all 6 fields)
**Problem:** All 6 fields in the financial tray read wrong keys. Frontend gets `[object Object]`, missing keys, or wrong names.

**File:** `dashboard/index.html` (the JS that reads the SSE data)

**Fields to fix:**
| Field | Current (broken) | Should be |
|---|---|---|
| Orders | `d.orders` (dict object) | `d.order_count` or serialize properly |
| Fills | `d.fills` (missing key) | `d.fill_count` |
| Positions | `d.positions` (wrong) | `d.open_positions` |
| Net P&L | `d.net_pnl` (wrong) | `d.realized_pnl` |
| Unrealized | check key | check BrainFrame field name |
| Daily loss | check key | check BrainFrame field name |

**Also fix:** `dashboard.py` — verify the `/api/state` or SSE payload actually includes these keys from BrainFrame.

**Done when:** Financial tray shows real numbers when engine is running DRY_RUN.

---

### 1-F: Fix SSE broadcast (single shared queue)
**Problem:** `state.sse_queue = Queue(maxsize=500)` — single queue shared across all browser tabs. Multiple tabs split events.

**File:** `dashboard.py`

**Change:** Replace single queue with per-client list:
```python
# Before
state.sse_queue = Queue(maxsize=500)

# After
state.sse_clients = []   # list of Queue objects, one per connected client

def sse_broadcast(event):
    for q in state.sse_clients[:]:
        try:
            q.put_nowait(event)
        except Full:
            pass  # slow client, drop

# In the /stream endpoint:
q = Queue(maxsize=200)
state.sse_clients.append(q)
try:
    yield from consume(q)
finally:
    state.sse_clients.remove(q)
```

**Done when:** Two open browser tabs both receive all events.

---

## Phase 2 — Fix Data Flow (P1 Silent Failures)

These make the optimizer see real data. Depends on Phase 1-C (TreasuryGland path fixed).

### 2-A: Wire P&L into optimizer fitness
**Problem:** `realized_fitness = (close - active_lo) / (active_hi - active_lo)` — Donchian position proxy. No P&L data flows into optimizer. DiamondGland selects for more breakout signals, not more profit.

**Files:** `Pituitary/search/diamond.py`, `Hippocampus/Archivist/synapse_scribe.py`

**Plan:**
1. `SynapseScribe` already has `realized_fitness` column in synapse_mint. Populate it from TreasuryGland PnL data at MINT time: look up the most recent completed trade for the symbol and compute `realized_pnl / risk_taken`.
2. `DiamondGland._compute_fitness()` reads `realized_fitness` from synapse_mint. Currently uses placeholder. Replace with the actual column value once it's populated.

**Done when:** `SELECT realized_fitness FROM synapse_mint` returns non-placeholder values that track actual trade outcomes.

---

### 2-B: Fix walk prior feedback (3 compounding failures)
**Problem:** TurtleWalk._mint_seed() calls `self.librarian.dispatch()` (doesn't exist), writes to `quantized_walk_mint` (no CREATE TABLE), WalkScribe reads `walk_mint` (different table).

**Files:** `Left_Hemisphere/Monte_Carlo/walk/service.py`, `Hippocampus/Archivist/walk_scribe.py`, `Hippocampus/Archivist/librarian.py`

**Fix:**
1. `walk/service.py`: Replace `self.librarian.dispatch(...)` with `self.librarian.write(sql, params)` (which exists)
2. `librarian.py` `_setup_mint_tables()`: Add `CREATE TABLE IF NOT EXISTS quantized_walk_mint (...)`
3. `walk_scribe.py`: Update table name from `walk_mint` to `quantized_walk_mint` (or unify to one name — pick `walk_mint` and fix the CREATE)

**Done when:** WalkScribe reads populated rows on the second pulse; `shock_source="silo_discharge"` appears in logs.

---

### 2-C: Fix VolumeFurnace promotion path
**Problem:** `VolumeFurnaceOrchestrator` fires every 3rd MINT but has no PituitaryGland reference. Stage H returns `promoted=True` → audit table only. Best inline optimizer results are never applied.

**File:** `Hospital/Optimizer_loop/volume_furnace_orchestrator/service.py`

**Change:** Pass PituitaryGland reference at construction (it's available in `_engine_loop`), and on promotion call `pituitary.promote_silver(candidate_params)`.

**Done when:** Stage H promotion writes new Silver to vault. Pituitary GP gets a better starting point.

---

### 2-D: Fix Pineal pruning targets
**Problem:** Pineal prunes `council_mint` and `turtle_monte_mint` from `Ecosystem_Memory.db` which is permanently empty. Actual tables are in `compat_librarian.db` (fixed to `Ecosystem_Memory.db` after 1-C).

**File:** `Hippocampus/pineal/service.py`

**After 1-C is done:** Pineal's target path should automatically be correct once TreasuryGland writes to `Ecosystem_Memory.db`. Verify `retention_map` paths match after the move.

**Done when:** Pineal `secrete_melatonin()` actually deletes rows from council_mint / turtle_monte_mint.

---

### 2-E: Fix WardManager Redis scan
**Problem:** `redis.keys("mammon:brain_frame:*")` — blocking O(N) scan. On boot, wipes ALL brain frames including other running instances if namespacing is ever reused.

**File:** `Cerebellum/Soul/utils/ward_manager.py`

**Change:** Replace `redis.keys()` with `redis.scan_iter()`:
```python
# Before
keys = self.redis.keys("mammon:brain_frame:*")

# After
keys = list(self.redis.scan_iter("mammon:brain_frame:*", count=100))
```
Also add run_id scoping: `f"mammon:brain_frame:{self.run_id}:*"` so a second instance doesn't wipe the first.

**Done when:** WardManager uses non-blocking scan; two simultaneous runs don't interfere.

---

## Phase 3 — Fix Signal Quality (P2)

These improve what the engine actually does. Safe to do after Phase 1 is stable.

### 3-A: Activate AllocationGland
`Medulla/allocation_gland/service.py` has a complete Kelly/equity-based sizing formula. It's never called. Gatekeeper hardcodes `sizing_mult = 0.01`.

**File:** `Medulla/gatekeeper/service.py`

Replace `sizing_mult = 0.01` with a call to `AllocationGland.compute(equity, risk_pct, conviction, stop_distance)`. Pass account equity from TreasuryGland.

---

### 3-B: Fix Brain Stem PARAM_KEYS
Two dead params in PARAM_KEYS (`brain_stem_survival`, `brain_stem_noise`). Four real behavioral params absent:
- `brain_stem_entry_max_z`
- `brain_stem_mean_dev_cancel_sigma`
- `brain_stem_stale_price_cancel_bps`
- `brain_stem_mean_rev_target_sigma`

**File:** `Hippocampus/Archivist/librarian.py` (the PARAM_KEYS list at top)

Remove the two dead ones. Add the four missing ones. GP now optimizes the real kill switches.

---

### 3-C: Fix Callosum dead weights
`callosum_w_adx` and `callosum_w_weak` are in PARAM_KEYS and logged to DB, but hardcoded to `0.5` and not used in the blend formula. GP wastes 2 dimensions on them.

**File:** `Corpus/callosum/service.py`

Either wire them into the blend formula (if intended) or remove them from PARAM_KEYS.

---

### 3-D: Fix Pineal archive-then-wipe transaction
**File:** `Hippocampus/pineal/service.py`

Wrap the INSERT + DELETE in a single transaction so INSERT failure doesn't cause silent data loss:
```python
with conn:   # sqlite3 context manager = transaction
    conn.execute("INSERT INTO synapse_mint SELECT * FROM history_synapse")
    conn.execute("DELETE FROM history_synapse")
```

---

### 3-E: Fix regime_id overwrite
Council writes `frame.risk.regime_id`. TurtleWalk overwrites with a different binning. TurtleWalk always wins.

**Files:** `Left_Hemisphere/Monte_Carlo/walk/service.py`

Either: write to a separate field (`frame.risk.walk_regime_id`) or use Council's value as the canonical one and remove the overwrite.

---

### 3-F: Add boot boundary countdown
**Problem:** Dashboard shows "Syncing to 5m boundary — waiting Xs" and goes silent for up to 5 minutes.

**File:** `dashboard.py` `_engine_loop`

During the wait loop, push a countdown SSE event every 30 seconds:
```python
while wait_sec > 0 and state.running:
    time.sleep(min(30.0, wait_sec))
    wait_sec = max(target - time.time(), 0)
    _push_sse({"type": "BOUNDARY_WAIT", "seconds_remaining": int(wait_sec)})
```

---

### 3-G: Tiers 2-4 (MomentumEngine, VelocityEngine, LevelsEngine)
Currently stub classes returning 0. System runs on Donchian breakout alone.

**Files:**
- `Right_Hemisphere/momentum/service.py`
- `Right_Hemisphere/velocity/service.py`
- `Right_Hemisphere/levels/service.py`

Implement or leave as stubs — but if stubs, remove them from PARAM_KEYS so GP doesn't try to optimize weights for them.

---

## Phase 4 — Polish (P3/P4)

Lower priority. Do after the engine is correctly recording data and the optimizer has real fitness.

| Task | File | What |
|---|---|---|
| 4-A DuckDB concurrent access | `Hippocampus/Archivist/librarian.py` | `get_duck_connection()` volatile fallback creates a new UUID DB on every lock fail — adds to the test artifact problem at runtime |
| 4-B Fornix dedup | `Hippocampus/fornix/service.py` | `history_synapse` loads with no dedup guard; replay can double-count |
| 4-C SpreadEngine circular ATR | `Cerebellum/council/spread_engine/service.py` | ATR uses spread-adjusted OHLC to compute ATR used to compute spread — circular |
| 4-D SmartGland state persistence | `Thalamus/gland/service.py` | bar count resets on restart, disrupting warmup state |
| 4-E Optical Tract backpressure | `Corpus/Optical_Tract/spray.py` | No subscriber count check; slow lobe blocks all others |
| 4-F pulse_log unbounded leak | `Cerebellum/Soul/orchestrator/service.py` | `pulse_log` list grows forever; add `maxlen=1000` deque |
| 4-G DiamondGland 24h window | `Pituitary/search/diamond.py` | Only looks at last 24h of synapse_mint; add configurable window |
| 4-H DuckPond cortex_precalc | `Hippocampus/duck_pond/service.py` | cortex_precalc never refreshed mid-run; stale after first pulse |

---

## Dependency Order

```
Phase 0 (cleanup) — no dependencies, do first
  │
  ├── 1-A (wire boot.py)
  ├── 1-B (TimescaleDB tables)   ← depends on 1-A
  ├── 1-C (TreasuryGland path)   ← unblocks 2-A, 2-D
  ├── 1-D (Telepathy fix)
  ├── 1-E (dashboard financial tray)
  └── 1-F (SSE broadcast)
       │
       ├── 2-A (P&L fitness)     ← needs 1-C
       ├── 2-B (walk feedback)
       ├── 2-C (VolumeFurnace)
       ├── 2-D (Pineal targets)  ← needs 1-C
       └── 2-E (WardManager)
            │
            Phase 3 (signal quality) — needs Phase 1 stable
            Phase 4 (polish) — anytime after Phase 1
```

---

## Done Criteria

The engine is "fixed" when:
1. `boot.py` runs on every start with no errors
2. `recent_pulses(10)` via MCP shows `realized_fitness` with non-placeholder values
3. `money_tape(10)` shows rows in `money_orders` in `Ecosystem_Memory.db` (not the hidden path)
4. Dashboard financial tray shows real numbers in DRY_RUN
5. `walk_mint` or `quantized_walk_mint` has rows after 3+ pulses
6. Pineal logs show actual row deletions from council_mint / turtle_monte_mint
