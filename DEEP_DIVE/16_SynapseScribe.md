# Deep Dive: SynapseScribe + SynapseRefinery — Synapse Write/Read Pair

## 1. Purpose & Role

These two classes form the **write/read pair** for the `Ecosystem_Synapse.db` SQLite store.

- **SynapseScribe** (`Hippocampus/Archivist/synapse_scribe.py`) — isolated SQLite writer for live MINT tickets. Used by Amygdala and Telepathy to commit per-pulse BrainFrame snapshots.
- **SynapseRefinery** (`Pituitary/refinery/service.py`) — harvests those tickets into a training DataFrame for DiamondGland, computing a `realized_fitness` proxy.

---

## 2. When Does Each Run?

| Component | Trigger | Frequency |
|---|---|---|
| SynapseScribe.mint() | Every MINT pulse (via Amygdala/Telepathy) | ~288×/day per symbol |
| SynapseRefinery.harvest_training_data() | Called by DiamondGland before Bayesian search | Once per Fornix post-replay |

---

## 3. SynapseScribe — Schema & Write Logic

**Fixed columns (declared at creation):**
`machine_code` (PK), `ts`, `symbol`, `pulse_type`, `execution_mode`, `open/high/low/close/volume/price`, `gear`, `tier1_signal`, `monte_score`, `tier_score`, `regime_id`, `council_score`, `atr`, `decision`, `approved`

**Schema is self-extending.** If a ticket contains a key not yet in the table, `_ensure_columns()` runs `ALTER TABLE ADD COLUMN` dynamically. Column type is inferred from the Python value type (bool→INTEGER, int→INTEGER, float→REAL, else TEXT).

**Write path:**
```
SynapseScribe.mint(ticket)
  → _ensure_columns(ticket)    # ALTER TABLE if new keys present
  → INSERT ... ON CONFLICT(machine_code) DO UPDATE SET ...
  → conn.commit()
```

`machine_code` is the natural idempotency key — replaying the same BrainFrame always upserts, not duplicates.

---

## 4. SynapseRefinery — Harvest & Fitness

```
SynapseRefinery.harvest_training_data(hours=24)
  → _resolve_time_filter()       # checks if column is 'created_at' or 'ts'
  → SELECT * FROM synapse_mint WHERE pulse_type='MINT' AND ts >= now - hours
  → df['realized_fitness'] = (close - active_lo) / (active_hi - active_lo)
      → fallback 0.5 if range = 0
  → return df
```

**Realized fitness formula:**
```
realized_fitness = (close - active_lo) / (active_hi - active_lo)
```
This measures where price closed within the active Donchian channel. A value near 1.0 means price closed near the top of its range (bullish); near 0 means it closed near the bottom.

**This is a placeholder.** The comment in the code explicitly acknowledges this: *"This is a placeholder; real fitness will correlate to P/L of the trade if approved."* DiamondGland's safety rails are derived from a proxy fitness metric, not actual P&L.

---

## 5. Dependencies

| Dependency | Direction | Purpose |
|---|---|---|
| `Ecosystem_Synapse.db` (SQLite) | read/write | Persistent synapse ticket store |
| `Librarian` (SQLite shim) | inbound (Refinery) | Read-only query interface |
| `Amygdala` / `Telepathy` | inbound (Scribe) | Calls mint() every MINT pulse |
| `DiamondGland` | outbound (Refinery) | Consumes harvest DataFrame |

---

## 6. Non-Obvious Behavior

- **`_ensure_columns` runs on every `mint()` call.** It issues a `PRAGMA table_info` query per write to check for new columns. At 288 writes/day this adds a PRAGMA round-trip to every commit — low cost individually but non-zero at scale.
- **`_resolve_time_filter()` introspects column names at harvest time.** If neither `created_at` nor `ts` column exists, the refinery falls back to no time filter — it returns ALL tickets regardless of age. This silently bypasses the `hours` parameter.
- **SynapseRefinery uses `Librarian` (SQLite shim), not `MultiTransportLibrarian`.** The `Librarian` class is the test/fallback SQLite shim. This means Refinery always reads directly from SQLite — no Redis layer, no hot vault — even in production.
- **`active_hi` and `active_lo` in the ticket reflect the Donchian channel at MINT time.** They are not forward-looking. The realized_fitness metric measures where price was at the moment of the pulse, not whether a trade placed at that moment was profitable.
- **dicts/lists in ticket values are JSON-serialized to TEXT.** Complex nested fields from BrainFrame are stored as JSON strings. DiamondGland training would need to parse these back — nothing in the current code does.

---

## 7. Open Questions / Risks

- **Fitness metric is disconnected from P&L.** A high `realized_fitness` (price near top of channel) does not mean a trade at that pulse would have been profitable. Rails derived from this signal could steer GP mutation toward unfavorable parameter regions.
- **No backfill of `realized_fitness` after trade outcome is known.** The fitness is computed at write time and never updated. Even if post-trade P&L data existed (e.g., in TreasuryGland), there is no mechanism to retroactively correct the training signal.
- **SQLite WAL contention.** SynapseScribe holds a persistent `sqlite3.connect()` connection. If multiple Soul instances (e.g., during parallel Fornix replay) open SynapseScribe on the same file, writes will serialize under SQLite's write lock — or fail with `database is locked`.
- **Schema drift.** The self-extending schema can accumulate phantom columns if BrainFrame fields change names between versions. Old columns are never dropped, and new columns create a sparse matrix where earlier rows have NULLs — this silently degrades GP training.

---

## 8. Deeper Investigation — Two Parallel Synapse Stores

This section documents findings from a second-pass code audit.

### Finding A: There are two `synapse_mint` tables that never talk to each other

**Store 1 — SQLite `Ecosystem_Synapse.db`:**
Written by `Amygdala → SynapseScribe.mint()`. This is the current live production path. Schema: ~20 fixed columns + self-extending. Read by `SynapseRefinery` via `Librarian` (SQLite shim). This is the chain that feeds DiamondGland and ParamCrawler.

**Store 2 — DuckDB `ecosystem_synapse.duckdb`:**
Created by `MultiTransportLibrarian._setup_mint_tables()`. Written by `librarian.mint_synapse()`. Has 47+ columns including all param columns, execution cost fields (`exec_expected_slippage_bps`, `exec_total_cost_bps`), spread fields, qty/notional, `cost_adjusted_conviction`, `mu/sigma/p_jump`. **Never written in the current production `service.py` path** — nothing calls `librarian.mint_synapse()` in live code.

These are structurally independent. The SQLite store is what the optimizer reads. The DuckDB store is what the target architecture will write to. Right now the richer table is always empty.

### Finding B: The DuckDB store has the data needed to ground fitness in execution reality

The DuckDB `synapse_mint` schema includes:
- `exec_expected_slippage_bps`, `exec_total_cost_bps` — actual cost of execution
- `qty`, `notional` — position sizing at time of MINT
- `cost_adjusted_conviction` — conviction after cost penalty
- All 47 param columns (the exact param set active at that MINT)

This is exactly what a real `realized_fitness` computation would need. The SQLite store has none of these fields. The optimization loop is reading from the poorer store.

### Finding C: Telepathy never actually routes DuckDB writes

`MultiTransportLibrarian.write()` calls:
```python
Telepathy().transmit(sql, params, transport=transport)
```

But `Telepathy.transmit(self, sql, params)` takes only 2 arguments — no `transport` parameter. Passing `transport=transport` as a keyword arg raises `TypeError`, caught by `except (ImportError, Exception)`, and falls through to `write_direct()`. **All MultiTransportLibrarian writes are synchronous via `write_direct()`.** The async Telepathy queue is bypassed for every DuckDB and TimescaleDB write.

Telepathy itself routes only to two SQLite files (`Ecosystem_Memory.db` and `Ecosystem_Synapse.db`) based on SQL text scanning. It has no DuckDB transport at all. The async system only serves SQLite writes from code that calls `Telepathy().transmit(sql, params)` directly — which appears to be nothing in the current production paths.

### The Migration Context

The `-TheBrain.py` file variants exist across the entire codebase. In `Amygdala/service-TheBrain.py`, Amygdala calls `self.lib.mint_synapse(ticket)` instead of `SynapseScribe.mint()` — migrating from SQLite to DuckDB. When that migration completes, SynapseRefinery will need to switch its read transport to DuckDB as well (currently it uses the SQLite `Librarian` shim). Until both sides are migrated together, switching Amygdala alone would break the optimization chain.

### What Needs to Happen

The migration path is:
1. Complete TheBrain Amygdala → DuckDB write
2. Update SynapseRefinery to use `MultiTransportLibrarian` with `transport="duckdb"` 
3. Fix the `realized_fitness` formula to use `exec_total_cost_bps`, `cost_adjusted_conviction`, and eventually P&L from TreasuryGland
4. Fix Telepathy's calling convention in `MultiTransportLibrarian.write()` (remove the `transport` kwarg from the `transmit()` call, or add it to `transmit()`'s signature)
