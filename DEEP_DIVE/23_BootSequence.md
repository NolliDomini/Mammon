# Deep Dive: Boot Sequence — From Click to First Pulse

## 1. Overview

Boot happens in four distinct phases. A user double-clicks `boot/Start_Mammon.bat` and the engine reaches its first live pulse roughly 5–7 minutes later (5-minute boundary sync plus container startup).

```
User double-clicks Start_Mammon.bat
  │
  ├── Phase 1: Infrastructure (BAT script)
  │     Python check → Docker check → .env onboarding → docker compose up
  │
  ├── Phase 2: Dashboard container startup (Python import time)
  │     MultiTransportLibrarian() → DuckDB tables created → Flask on port 5000
  │
  ├── Phase 3: User clicks START DRY RUN (browser action)
  │     _require_infra() → Redis + TimescaleDB ping → _engine_loop thread spawned
  │
  └── Phase 4: Engine loop initialization
        WardManager sweep → Vault load → Lobes registered → 5-minute boundary wait
        → First pulse
```

---

## 2. Phase 1 — `boot/Start_Mammon.bat`

```
1. python --version                          # fails hard if Python not in PATH
2. docker --version                          # fails hard if Docker CLI missing
3. docker info                               # fails hard if Docker daemon not running
4. if not .env exists:
     python boot/onboard.py                  # interactive: prompts for Alpaca keys
       → reads .env.example (if exists)
       → substitutes API key/secret
       → generates MAMMON_API_TOKEN (secrets.token_hex(16))
       → generates MAMMON_ADMIN_TOKEN (secrets.token_hex(16))
       → writes .env
5. if not Desktop\Mammon.lnk exists:
     powershell CreateShortcut → one-time shortcut creation
6. docker compose -f ../docker-compose.yml up -d --remove-orphans
     → mammon-redis    (redis:7-alpine, port 6379, volume mammon-redis-data)
     → mammon-timescale (timescaledb:latest-pg14, port 55432, volume mammon-timescale-data)
     → mammon-dashboard (built from Dockerfile, port 5000, mounts .:/mammon)
7. Poll http://localhost:5000/__health every 2s, up to 30 retries (60s timeout)
8. Read MAMMON_API_TOKEN from .env
9. start browser: http://localhost:5000/?token=TOKEN
```

### What `boot.py` does (and doesn't do)

`boot/onboard.py` creates `.env`. **`boot.py` (the `MammonBootstrapper`) is a separate standalone script — it is NOT called by `Start_Mammon.bat`.** It performs:
- Environment variable validation
- Redis + DuckDB + TimescaleDB handshake
- Schema smoke check (`run_schema_smoke_check()`) — creates missing DB files, stamps schema versions, checks for table drift

Because `boot.py` is not wired in, **the normal boot path performs no schema validation**. If tables are missing or schema has drifted, the system starts silently and errors appear at first write.

---

## 3. Phase 2 — Dashboard Container Startup

When `mammon-dashboard` starts, Python imports `dashboard.py`. At module import time:

```python
# librarian.py bottom
librarian = MultiTransportLibrarian()          # runs __init__ immediately
```

`MultiTransportLibrarian.__init__()` runs before Flask even starts:
```
Creates Hippocampus/data/ directory (mkdir parents=True)
Opens ecosystem_synapse.duckdb            → Hippocampus/data/ecosystem_synapse.duckdb
Opens ecosystem_params.duckdb             → Hippocampus/data/ecosystem_params.duckdb
_setup_param_tables()
  → CREATE TABLE IF NOT EXISTS param_sets (id, tier, params_json, ...)
_setup_mint_tables()
  → CREATE TABLE IF NOT EXISTS walk_mint
  → CREATE TABLE IF NOT EXISTS monte_mint
  → CREATE TABLE IF NOT EXISTS optimizer_mint
  → CREATE TABLE IF NOT EXISTS synapse_mint (47 param columns + all BrainFrame slots)
  → CREATE INDEX idx_synapse_mint_machine_code
  → CREATE TABLE IF NOT EXISTS optimizer_stage_audit
  → CREATE TABLE IF NOT EXISTS optimizer_candidate_library
  → CREATE TABLE IF NOT EXISTS opt_stage_runs, opt_scores_components, opt_diversity_metrics,
                                 opt_regime_coverage, opt_promotion_decisions
_run_migrations()
  → ALTER TABLE synapse_mint ADD COLUMN {bid, ask, val_mean, ...}   (silent if already exists)
  → ALTER TABLE money_orders ADD COLUMN ... transport="timescale"   (silent fail — table doesn't exist on TimescaleDB)
```

Flask then starts on port 5000. `/__health` returns "ok" immediately.

**What is NOT created at this point:**
- `Hospital/Memory_care/duck.db` — the Fornix/Hospital DuckDB. Only created by SchemaGuard (`boot.py`) or by Fornix's first run.
- `Hospital/Memory_care/control_logs.db` — same.
- `Hippocampus/data/Ecosystem_UI.db` — same.
- `Hippocampus/Archivist/Ecosystem_Memory.db` — created on first Telepathy SQLite write.
- `runtime/.tmp_test_local/compat_librarian.db` — created by TreasuryGland on first instantiation.
- TimescaleDB tables — **never auto-created**. `_require_infra()` only pings `SELECT 1`. `money_orders` and other TimescaleDB tables do not exist unless created manually.

---

## 4. Phase 3 — User Clicks START DRY RUN

Browser POST to `/api/start` with `{mode: 'DRY_RUN', symbols: ['BTC/USD']}`.

```python
_require_infra():
  librarian.get_redis_connection().ping()        # hard fail if Redis unreachable
  librarian.get_timescale_connection()           # hard fail if TimescaleDB unreachable
  ts_conn.cursor().execute("SELECT 1")           # table existence NOT checked

state.mode = 'DRY_RUN'
state.run_id = uuid4().hex[:8]
state.running = True
threading.Thread(target=_engine_loop, ...).start()
return 200 immediately
```

**Critical:** `_require_infra()` blocks engine start for **both Redis AND TimescaleDB** regardless of mode. DRY_RUN has the same infra requirements as LIVE. There is no offline or local-only mode. If TimescaleDB is slow to start (container cold start), the user will get a 500 error and need to retry.

---

## 5. Phase 4 — `_engine_loop` Thread Initialization

```python
# 1. Module imports (all lobes loaded into memory)
from Thalamus.relay.service import Thalamus
from Cerebellum.Soul.orchestrator.service import Orchestrator
from Corpus.Optical_Tract.spray import OpticalTract
from Right_Hemisphere.Snapping_Turtle.engine.service import SnappingTurtle
from Cerebellum.council.service import Council
from Left_Hemisphere.Monte_Carlo.turtle.service import TurtleMonte
from Corpus.callosum.service import Callosum
from Medulla.gatekeeper.service import Gatekeeper
from Brain_Stem.trigger.service import Trigger
from Hippocampus.telepathy.service import Telepathy

# 2. Start async persistence (Scribe Daemon for SQLite writes)
_telepathy = Telepathy()                   # singleton; starts ScribeDaemon thread
                                           # routes to Ecosystem_Memory.db + Ecosystem_Synapse.db

# 3. Build Optical Tract → Soul subscription
tract = OpticalTract()

# 4. Orchestrator.__init__()
Orchestrator(
  optical_tract=tract,
  config={
    "trading_enabled_provider": lambda: state.trading_enabled,
    "execution_mode": "DRY_RUN",
    "synapse_persist_pulse_types": ["SEED","ACTION","MINT"],  # from env
  }
)
  │
  ├── WardManager().janitor_sweep()
  │     redis.keys("mammon:brain_frame:*")    # O(N) Redis scan
  │     redis.delete(*keys)                   # wipes ALL brain frames, all modes
  │
  ├── self.vault = self._load_vault()
  │     librarian.get_hormonal_vault()
  │       → Redis GET mammon:hormonal_vault
  │       → if key missing: reads hormonal_vault.json → normalizes → writes to Redis
  │       → if vault.json also missing: returns skeleton with Gold id="UNKNOWN", params={}
  │         ⚠ Empty params means all lobes start with zero config → gear=0 → no trading
  │
  ├── self.frame = BrainFrame()              # all slots zero
  ├── self.frame.standards = gold["params"]  # empty if no vault
  ├── self.frame.market.execution_mode = "DRY_RUN"
  │
  ├── QuantizedGeometricWalk()               # walk engine instantiated
  ├── VolumeFurnaceOrchestrator(simulation_mode=False, execution_mode="DRY_RUN")
  │     # inline optimizer ready; fires every 3rd MINT
  │
  ├── Amygdala(config={synapse_persist_pulse_types: ["SEED","ACTION","MINT"]})
  │     SynapseScribe(db_path=Hippocampus/Archivist/Ecosystem_Synapse.db)
  │       → sqlite3.connect(Ecosystem_Synapse.db)   # creates file if missing
  │       → CREATE TABLE IF NOT EXISTS synapse_mint  # 20 fixed cols
  │
  ├── Pineal(config={...})
  ├── PituitaryGland()
  ├── ParamCrawler()  (if importable; soft fail if not)
  └── OptimizerLibrarian()

# 5. Register lobes (all initialized with Gold params from vault)
gold = vault["gold"]["params"]                # empty dict if no vault
orchestrator.register_lobe("Right_Hemisphere", SnappingTurtle(config=gold))
orchestrator.register_lobe("Council",          Council(config=gold, mode="DRY_RUN"))
orchestrator.register_lobe("Left_Hemisphere",  TurtleMonte(config=gold, mode="DRY_RUN"))
orchestrator.register_lobe("Corpus",           Callosum(config=gold, mode="DRY_RUN"))
orchestrator.register_lobe("Gatekeeper",       Gatekeeper(config=gold, mode="DRY_RUN"))
orchestrator.register_lobe("Brain_Stem",
  Trigger(
    api_key=ALPACA_API_KEY,
    api_secret=ALPACA_API_SECRET,
    paper=True,                              # DRY_RUN → paper=True → no real orders
    config={
      "execution_mode": "DRY_RUN",
      "max_notional_per_order": float(env.MAMMON_MAX_NOTIONAL_PER_ORDER or 0),
      "max_open_positions":     int(env.MAMMON_MAX_OPEN_POSITIONS or 0),
      "max_daily_realized_loss": float(env.MAMMON_MAX_DAILY_REALIZED_LOSS or 0),
      **gold,
    }
  )
)
thalamus = Thalamus(api_key=..., api_secret=..., optical_tract=tract)
orchestrator.register_lobe("Thalamus", thalamus)

# 6. Push ENGINE_STARTED event to SSE → browser shows "Engine started in mode=DRY_RUN"
# 7. Write ENGINE_STARTED to runtime/logs/engine_lifecycle.jsonl

# 8. Wait for next 5-minute boundary
now_ts = time.time()
target = math.ceil(now_ts / 300) * 300      # rounds up to next :00 or :05 or :10...
wait_sec = target - time.time()             # 0 to 299 seconds

# Dashboard shows: "Syncing to 5m boundary — waiting Xs"
# Brain Frame panels show zeros during this entire wait
# No visible countdown beyond the static message

while wait_sec > 0 and state.running:
    time.sleep(min(1.0, wait_sec))
    wait_sec = max(target - time.time(), 0)

# 9. Enter poll loop (0.5s interval) — first real pulse fires after boundary
```

---

## 6. Prerequisites Checklist

| Requirement | Source | If Missing |
|---|---|---|
| Docker Desktop installed + running | User installs | BAT exits at step 3 with error |
| Python 3.12+ in PATH | User installs | BAT exits at step 1 |
| `.env` with `ALPACA_API_KEY` + `ALPACA_API_SECRET` | `onboard.py` creates on first run | `_check_env()` in `boot.py` fails; `_engine_loop` has no API key |
| `REDIS_HOST` / `TIMESCALE_HOST` in env | Set by docker-compose environment override | Defaults to `localhost`; correct inside container via compose |
| Redis container healthy | docker-compose | `_require_infra()` fails → START returns 500 |
| TimescaleDB container healthy | docker-compose | `_require_infra()` fails → START returns 500 |
| `Hippocampus/hormonal_vault.json` with valid Gold | Ships with repo | System starts with `params: {}` → gear=0 → no trading ever |
| `MAMMON_API_TOKEN` in `.env` | `onboard.py` generates | Browser opens without token → all API calls 401 |

---

## 7. First-Run State After Phase 4

After a clean install, the first run has:

| State | Value | Consequence |
|---|---|---|
| Gold params | Populated from `hormonal_vault.json` | Determines all lobe behavior |
| Silver | Empty or from prior vault | Pituitary GP has 1-point training set on first run |
| Platinum | None | No Hospital winner yet |
| `Ecosystem_Synapse.db` | Empty | DiamondGland / ParamCrawler MINE have no training data |
| `ecosystem_synapse.duckdb` → `synapse_mint` | Empty | TheBrain migration target; unused |
| `ecosystem_params.duckdb` → `param_sets` | Empty | No param lineage yet |
| `Hospital/Memory_care/duck.db` | Does not exist | Fornix batch will fail on first run |
| Redis vault | Loaded from `hormonal_vault.json` | Correct |
| Brain Frame | All slots zero | Correct — lobes populate on first pulse |

---

## 8. Boot Issues / Gaps

### Issue 1: `boot.py` not in the flow
`MammonBootstrapper.run_handshake()` does all the right things: env check, Redis ping, DuckDB check, TimescaleDB check, schema smoke check. It is never called by `Start_Mammon.bat`. Schema drift and missing tables go undetected until the first write fails.

**Fix:** Add `python ../boot.py` call to `Start_Mammon.bat` before the docker-compose step (or as part of the dashboard container entrypoint before Flask starts).

### Issue 2: TimescaleDB tables never created
`_require_infra()` only pings `SELECT 1`. The `money_orders` table (and all other TimescaleDB audit tables) do not exist. `_run_migrations()` attempts `ALTER TABLE money_orders ADD COLUMN ...` but fails silently. TreasuryGland uses the SQLite shim so it never hits TimescaleDB — but if any code ever routes to TimescaleDB transport, it will get table-not-found errors silently swallowed.

**Fix:** Add a TimescaleDB migration script to the startup sequence that creates `money_orders`, `trade_intents`, `broadcast_audit` tables on first run.

### Issue 3: `Hospital/Memory_care/` never created
The Fornix batch optimizer's DuckDB (`duck.db`) is never touched by the normal boot. Running Fornix on a fresh install will fail with a directory-not-found or schema error.

**Fix:** `ensure_schema_versions()` in `boot.py` creates this directory and the DB file. Wiring `boot.py` into startup fixes this automatically.

### Issue 4: TreasuryGland in a hidden temp path
TreasuryGland instantiates `Librarian()` with no path argument. The SQLite file lands at `runtime/.tmp_test_local/compat_librarian.db`. This is inside the Docker volume mount (`.:/mammon`) so it persists across restarts — but it is in a hidden path that is not obvious to inspect, back up, or monitor.

**Fix:** Pass an explicit `db_path` to TreasuryGland pointing to `Hippocampus/Archivist/Ecosystem_Memory.db` (the path SchemaGuard expects and monitors).

### Issue 5: 5-minute silent wait
After the engine starts, the dashboard shows "Syncing to 5m boundary — waiting Xs" and goes quiet. No countdown timer. The user sees a blank Brain Frame for up to 5 minutes with no indication of progress.

**Fix:** Push a countdown tick event to SSE every 30 seconds during the wait, or add a visible browser-side countdown from the initial `wait_sec` value.

### Issue 6: Empty vault on first install means no trading
If `hormonal_vault.json` exists but has `params: {}` (or only has an "UNKNOWN" Gold), all lobes start with zero config. `active_gear = 0` → Right Hemisphere safe-resets every pulse → `tier1_signal = 0` → no pipeline fires. The system runs but never trades. There is no warning.

**Fix:** `Start_Mammon.bat` or `onboard.py` should verify `hormonal_vault.json` exists and has a non-empty Gold entry, or seed it from a known-good default profile.

---

## 9. Sequence Timeline (Happy Path)

```
T+0:00   User double-clicks Start_Mammon.bat
T+0:05   .env check complete (or onboarding prompt)
T+0:10   docker compose up issued
T+0:30   Redis container healthy
T+0:45   TimescaleDB container healthy  (PostgreSQL init takes ~15-30s)
T+0:50   dashboard container Python import completes; DuckDB tables created
T+0:55   Flask health endpoint responds
T+1:00   BAT opens browser; user sees dashboard
T+1:10   User clicks START DRY RUN
T+1:11   _require_infra() passes (both infra healthy)
T+1:12   _engine_loop thread spawned
T+1:15   Orchestrator.__init__ complete; all lobes registered
T+1:16   Dashboard shows "Syncing to 5m boundary — waiting Xs"
         (up to 299 seconds of silent wait)
T+6:16   First 5-minute boundary reached
T+6:17   Poll loop starts; first Alpaca bar request
T+6:18   First real pulse; Brain Frame panels populate
```

Worst case (just missed a boundary): 5-minute wait → first pulse at T+11.
