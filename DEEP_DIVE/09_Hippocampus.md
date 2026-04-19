# Deep Dive: Hippocampus — Memory & Persistence Layer

## 1. Purpose & Role
Hippocampus is the **persistence substrate** for the entire system. Every lobe that writes to disk, reads history, or sends async logs goes through here. It has no trading logic — it is pure infrastructure.

---

## 2. Architecture: Three Transport Layers

| Transport | Technology | Purpose |
|---|---|---|
| **DuckDB** | `ecosystem_synapse.duckdb` | Analytical store — all mint tables, pulse snapshots, walk/monte logs |
| **Redis** | `mammon:hormonal_vault` hash | Live vault — Gold params hot-reload source |
| **TimescaleDB** | PostgreSQL + timescale | Immutable audit ledger — `money_orders`, `broadcast_audit` |

**In local/test mode**: TimescaleDB writes are silently re-routed to DuckDB via SQL normalization (`%s → ?`, `DOUBLE PRECISION → DOUBLE`). Redis fails hard in LIVE/PAPER modes.

---

## 3. Key Components

### MultiTransportLibrarian (singleton)
The **central data gateway**. One instance shared across all lobes (singleton pattern via `__new__`). Provides:
- `write()` → routes through Telepathy (async, fire-and-forget)
- `write_direct()` → bypasses Telepathy (synchronous, immediate)
- `read()` / `read_only()` / `query()` — synchronous reads
- `get_duck_connection()` — raw DuckDB connection
- `get_redis_connection()` → fails hard if unavailable in LIVE/PAPER
- `get_timescale_connection()` → fails hard if unavailable in LIVE/PAPER
- `get_hormonal_vault()` → reads from Redis, bootstraps from JSON if missing
- `dispatch()` → alias used by some lobes (maps to `write()`)

**Important**: `Librarian` (lowercase, no `Multi`) is a **separate lightweight SQLite-backed class** for isolated tests. Many lobes import `from Hippocampus.Archivist.librarian import Librarian` and get the test shim, not `MultiTransportLibrarian`. The singleton `librarian` (module-level instance) is `MultiTransportLibrarian`.

### Telepathy (async write queue)
**Fire-and-forget write bus**. All `librarian.write()` calls are enqueued here.
- Singleton background thread (`ScribeDaemon`)
- Bounded queue: 10,000 items max — drops oldest on overflow (with counter)
- Batch size: 500 items, flush interval 0.5s
- Routes by SQL content: `synapse_mint` / `history_synapse` → `Ecosystem_Synapse.db`, everything else → `Ecosystem_Memory.db`
- Exponential backoff on SQLite lock contention (0.1s → 1.6s, 5 retries)
- **Writes to SQLite**, not DuckDB — Telepathy's vaults are `Ecosystem_Memory.db` and `Ecosystem_Synapse.db` (SQLite files), separate from `ecosystem_synapse.duckdb`

### Amygdala (BrainFrame state scribe)
Writes full `BrainFrame` snapshots to `Ecosystem_Synapse.db` as **synapse tickets**.
- Called by Soul after every pulse: `mint_synapse_ticket(pulse_type, frame)`
- Default: only persists `MINT` pulses (configurable via `synapse_persist_pulse_types`)
- Validates 20 required keys before writing; rejects on missing keys or wrong pulse type
- Deduplication: `machine_code` is SHA-256 of (mode, pulse, symbol, regime, decision, ts) — used as primary key

### DuckPond (raw bar persistence)
Writes live 1m and 5m OHLCV bars from Thalamus.
- `append_live_bars(df)` → raw 1m bars
- `append_live_5m_bars(df)` → finalized 5m OHLCV on MINT
- Injected into Thalamus at construction — optional

---

## 4. DuckDB Table Map

| Table | Written by | Content |
|---|---|---|
| `synapse_mint` | Amygdala | Full BrainFrame snapshot per MINT (47 param cols + all slots) |
| `walk_mint` / `quantized_walk_mint` | QuantizedGeometricWalk | WalkSeed per pulse |
| `turtle_monte_mint` | TurtleMonte | Monte simulation result per pulse |
| `callosum_mint` | Callosum | Tier synthesis scores |
| `gatekeeper_mint` | Gatekeeper | Approval decisions |
| `broadcast_audit` | OpticalTract | Failed spray deliveries |
| `money_orders` | TreasuryGland | Intent → fire lifecycle (TimescaleDB, local-routed to DuckDB) |
| `param_sets` | Librarian | Gold/Silver/Bronze param sets (`ecosystem_params.duckdb`) |
| `cortex_precalc` | Council | Batch pre-computed indicators |

---

## 5. Hormonal Vault

`hormonal_vault.json` is the **Gold params source of truth**. Loaded at Soul boot, re-read at every MINT via `_check_vault_mutation()`.

- **File** (`Hippocampus/hormonal_vault.json`) → read at boot and on hot-reload
- **Redis** (`mammon:hormonal_vault` hash) → live read via `librarian.get_hormonal_vault()` (Council uses this path)
- Redis bootstraps from JSON if key missing

---

## 6. Other Components

| Component | Purpose |
|---|---|
| `Pineal` | MINT-cycle memory secretion — writes to `pineal_mint` table, manages melatonin state |
| `Fornix` | Trade gate / warmup guard — `is_trading_enabled()`, warmup bar counting |
| `SchemaGuard` | DB schema validation utility |
| `WalkScribe` | Walk Silo — writes/reads historical mutations for QuantizedGeometricWalk |
| `OptimizerLibrarian` | Optimizer-specific writes (stage runs, candidates, promotions) |
| `ParamCrawler` | MINT-cycle param scoring — reads synapse history, scores candidates |

---

## 7. Failure Modes

- **DuckDB locked**: falls back to volatile temp file (`runtime/.tmp_test_local/`) — data is lost on restart
- **Redis unavailable in LIVE/PAPER**: hard `ConnectionError` — system will not start without Redis in production
- **TimescaleDB unavailable in LIVE/PAPER**: hard `ConnectionError`
- **Telepathy queue full**: drops oldest item (OOM guard) — audit data silently lost
- **Amygdala validation failure**: ticket rejected, `last_write_status = "REJECTED_VALIDATION"`, no crash

---

## 8. Non-Obvious Behavior

- **`Librarian` vs `librarian` vs `MultiTransportLibrarian`**: three names, two classes. `librarian` (module-level singleton) is `MultiTransportLibrarian`. The class `Librarian` is the SQLite test shim. Most lobes that call `Librarian()` at runtime get a per-instance SQLite connection, not the shared DuckDB gateway.
- **Telepathy routes by SQL text scanning** (`"synapse_mint" in sql.lower()`) — a table rename would silently break routing to the wrong vault.
- **Two separate DuckDB files**: `ecosystem_synapse.duckdb` (main analytical, via `get_duck_connection()`) and `ecosystem_params.duckdb` (param sets, via `get_param_connection()`). They are never joined.
- **`dispatch()` does not exist on either Librarian class.** There is no `dispatch()` method on `Librarian` (SQLite shim) or `MultiTransportLibrarian`. Any lobe calling `self.librarian.dispatch()` gets an `AttributeError` silently swallowed by the caller's `except Exception: pass` guard. No write happens. This affects TurtleWalk's walk prior persistence — confirmed dead.
- **DuckDB compat shim** (`_install_duckdb_compat_shim`) patches `duckdb.connect` globally at import time to intercept `PRAGMA` and `EXPLAIN QUERY PLAN` calls — prevents test failures but modifies a global.

---

## 9. Open Questions / Risks

- **Telepathy writes to SQLite, not DuckDB** — the main analytical store (`ecosystem_synapse.duckdb`) and the async write targets (`Ecosystem_Synapse.db`, `Ecosystem_Memory.db`) are different files with different formats. Queries on DuckDB won't see async-written data until it's also written to DuckDB directly.
- **`Librarian` class (test shim) is used in production lobes** — TurtleMonte, Council, Callosum, Gatekeeper all instantiate `Librarian()` directly, getting per-instance SQLite connections rather than the shared DuckDB singleton.
- **Queue drop is silent after every 100th drop** — in a saturated system, thousands of audit records can be lost with only periodic console output.
- **Fornix/warmup gate** — `is_trading_enabled()` is the runtime trade gate injected into Soul. If Fornix is not wired, the gate defaults to `True` (trade always enabled).

---

## 10. Deeper Investigation — Telepathy is Bypassed and the System is Mid-Migration

### Finding A: Telepathy never receives DuckDB or TimescaleDB writes

`MultiTransportLibrarian.write()`:
```python
Telepathy().transmit(sql, params, transport=transport)
```

`Telepathy.transmit(self, sql: str, params: Any)` — **no `transport` parameter**. Passing `transport=transport` as a keyword argument raises `TypeError`. This is caught by `except (ImportError, Exception)` and falls through to `write_direct()`.

**Every call to `librarian.write()` is synchronous via `write_direct()`.** The async Telepathy queue is never used for DuckDB or TimescaleDB writes. The 10,000-item queue, the batching logic, and the bounded-backoff retry code — all operational, none of it receiving traffic from the main data path.

Telepathy itself only routes to two SQLite vaults (`Ecosystem_Memory.db` and `Ecosystem_Synapse.db`). Any code that calls `Telepathy().transmit(sql, params)` directly (without the broken `transport` kwarg) would work correctly for SQLite targets. In the current production paths, nothing does this — `transmit()` is never called directly.

### Finding B: The system is systematically mid-migration

Every meaningful module has two versions: `service.py` (current production) and `service-TheBrain.py` (target architecture). The pattern is consistent across 40+ files including Amygdala, TurtleWalk, Soul, Pineal, Brain Stem, Thalamus, DuckPond, Fornix, DiamondGland, Pituitary, Hospital optimizer, and all test contracts.

The TheBrain architecture:
- Amygdala writes to DuckDB via `librarian.mint_synapse()` instead of SQLite via SynapseScribe
- Walk priors go to DuckDB `walk_mint` via a corrected write path
- Pineal purges DuckDB tables directly instead of SQLite
- Telepathy is either fixed or replaced

**The current `service.py` production files are the legacy architecture.** The subsystems documented as "broken" (walk prior feedback, async Telepathy, DuckDB synapse store) are broken because the migration is partially complete — read paths point at TheBrain targets while write paths still use the legacy approach.

### Implication for the Optimization Loop

Until the migration completes:
- DiamondGland and ParamCrawler train on SQLite synapse tickets (Amygdala → SynapseScribe path) ✓ consistent, but limited schema
- Walk prior feedback (WalkScribe → TurtleWalk) is non-functional — Monte Carlo always uses defaults
- The richer DuckDB synapse schema (slippage, costs, param columns) is inaccessible to the optimizer

The safe cut-over requires migrating Amygdala write AND SynapseRefinery read to DuckDB simultaneously, or the optimizer temporarily loses its training data.
