# Deep Dive: WalkScribe — Regime-Keyed Walk Prior Reader

## 1. Purpose & Role
WalkScribe is the **read interface for historical walk priors**. TurtleWalk (Left Hemisphere) writes Lévy walk parameters into `walk_mint` (DuckDB) every pulse; WalkScribe reads them back at the next pulse to seed the Monte Carlo shock distribution with regime-specific historical priors rather than default parameters.

It is a compatibility reader — its entire implementation is one method (`discharge()`).

---

## 2. When Does It Run?

Called by `TurtleWalk.generate()` during every ACTION/MINT pulse in live mode. Instantiated lazily on first use (only after `regime_id` is known).

```
TurtleWalk.generate()
  → if self.scribe is None: self.scribe = WalkScribe(regime_id, run_id)
  → pulled = self.scribe.discharge(regime_id, limit=35000)
```

In **BACKTEST mode**, `discharge()` is bypassed entirely — the shocks come from the BrainFrame directly (`frame_shocks`).

---

## 3. The `walk_mint` Table (DuckDB)

Written by `MultiTransportLibrarian._write_walk_mint()` via the Telepathy async queue:

| Column | Type | Purpose |
|---|---|---|
| `ts` | TIMESTAMP | Write time |
| `symbol` | VARCHAR | Ticker |
| `regime_id` | VARCHAR | D_A_V_T string (Council computed) |
| `mu` | DOUBLE | Drift parameter |
| `sigma` | DOUBLE | Volatility parameter |
| `p_jump` | DOUBLE | Jump probability |
| `confidence` | DOUBLE | Council confidence at write time |
| `mode` | VARCHAR | LIVE / BACKTEST |
| `pulse_type` | VARCHAR | ACTION / MINT |

---

## 4. `discharge()` — The Read Path

```
WalkScribe.discharge(regime_id, limit=35000)
  → SELECT mu FROM walk_mint
    WHERE regime_id = ?
    ORDER BY ts DESC LIMIT 35000
  → [float(r[0]) for r in rows]
  → on any exception: return []
```

Returns a list of raw `mu` (drift) values — the most recent 35,000 walk priors for that regime ID. TurtleWalk uses these as the shock mutation set for the Monte Carlo paths.

---

## 5. Shock Source Priority (TurtleWalk)

TurtleWalk picks its shock distribution from these sources in order:

1. **BACKTEST mode + frame_shocks** — historical shocks from BrainFrame (highest fidelity)
2. **`discharge()` returns data** — live regime-specific priors from DuckDB (`silo_discharge`)
3. **frame_shocks in live mode** — real-time shocks from the current frame (`frame_live`)
4. **Default WalkSeed parameters** — hard-coded fallback if all else fails

---

## 6. Dependencies

| Dependency | Direction | Purpose |
|---|---|---|
| `walk_mint` (DuckDB) | read | Source of regime-keyed walk priors |
| `MultiTransportLibrarian` | inbound | `librarian.read(sql, params, transport="duckdb")` |
| `TurtleWalk` | consumer | Calls discharge() to get shock mutations |

---

## 7. Non-Obvious Behavior

- **Reads only `mu`, ignores `sigma`/`p_jump`.** The query selects only the drift column. The variance and jump parameters written at mint time are not used when reconstituting the shock distribution — the distribution is effectively built from drift values alone.
- **35,000-row limit is regime-specific.** In a narrow D_A_V_T regime with few historical matches, discharge may return only a handful of values. TurtleWalk treats this as valid input — a very small shock set reduces Monte Carlo diversity.
- **`transport="duckdb"` explicit.** WalkScribe forces DuckDB transport, bypassing Redis and SQLite entirely. This is correct — `walk_mint` lives only in DuckDB.
- **Exceptions are silently swallowed.** Any failure (table missing, connection error, DuckDB lock) returns `[]`. TurtleWalk falls back to `frame_shocks` or defaults — the caller never knows discharge failed.
- **`run_id` is stored on the instance but never used.** It was likely intended for filtering priors by optimization run, but the `discharge()` query ignores it.
- **Instantiated per-TurtleWalk instance.** Each Soul pipeline rebuild (every Fornix symbol) creates a fresh TurtleWalk and thus a fresh WalkScribe — the regime_id passed at construction may be stale by the first actual discharge call (which passes regime_id as a parameter anyway).

---

## 8. Open Questions / Risks

- **Only `mu` is replayed.** If the walk distribution is non-Gaussian (fat tails, jumps), using only drift values as the shock set loses the tail behavior that `p_jump` and `sigma` encode. Monte Carlo paths in live mode may underestimate tail risk relative to the calibrated model.
- **Regime ID granularity.** The D_A_V_T regime string is 4-dimensional — some combinations may have zero historical priors. In a new market regime, discharge always returns `[]`, and TurtleWalk silently falls back to defaults with no alerting.
- **No TTL on walk_mint reads.** The query returns the 35,000 most recent rows globally — if walk_mint grows large and old regimes are never purged (Pineal only purges SQLite, not DuckDB walk_mint directly), stale priors from defunct regimes accumulate and are never read.

---

## 9. Deeper Investigation — Walk Prior Feedback is Completely Dead

This section documents findings from a second-pass code audit that goes beyond the original questions.

### Finding A: TurtleWalk writes to a table that doesn't exist

`TurtleWalk._mint_seed()` calls:
```python
self.librarian.dispatch("""
    INSERT INTO quantized_walk_mint (...)
""", ...)
```

`self.librarian` is a `Librarian` (SQLite shim) instance. `Librarian` has no `dispatch()` method — it has `write()`, `read()`, `read_only()`. Calling `dispatch()` raises `AttributeError`, which is silently caught:

```python
except Exception:
    # Walk persistence is audit-only and must never block risk painting.
    pass
```

**No walk priors are ever written in the current production codebase.** Every call to `_mint_seed()` silently fails.

### Finding B: Wrong table name even if the write worked

`TurtleWalk` attempts to write to `quantized_walk_mint`. `WalkScribe` reads from `walk_mint`. These are different tables.

- `walk_mint` — created by `MultiTransportLibrarian._setup_mint_tables()` in DuckDB. Has a `mint_walk()` write method on the librarian, but that method is never called in any live production path.
- `quantized_walk_mint` — referenced by TurtleWalk writes and by Pineal's SQLite retention purge. Has no CREATE TABLE statement anywhere in the current codebase — the table definition doesn't exist.

Even if `dispatch()` existed and the write succeeded, WalkScribe would never see the data because it queries the wrong table name via DuckDB.

### Finding C: `shock_source = "silo_discharge"` is never hit

WalkScribe.discharge() always returns `[]` because `walk_mint` in DuckDB is permanently empty. TurtleWalk's shock source priority collapses to:

- BACKTEST: `frame_shocks` (BrainFrame historical shocks)
- LIVE: `frame_shocks` if present, else hard-coded WalkSeed defaults

The regime-aware trajectory prior system — the entire point of WalkScribe — has no effect on Monte Carlo path generation in either mode.

### The Migration Context

The `-TheBrain.py` file variants exist for virtually every module in the codebase. `Pineal/service-TheBrain.py` purges `walk_mint` (DuckDB), not `quantized_walk_mint` (SQLite) — the TheBrain target architecture consolidates walk priors into DuckDB `walk_mint` and fixes the write path. `TurtleWalk/service-TheBrain.py` presumably calls a working write method.

The current `service.py` files are mid-migration: the read infrastructure (WalkScribe → DuckDB `walk_mint`) is already pointed at the TheBrain target, but the write infrastructure still references the legacy `quantized_walk_mint` table via a non-existent `dispatch()` method.

### What Needs to Happen

1. Add a `dispatch()` method to `Librarian`, or replace `self.librarian.dispatch()` with `self.librarian.write()` in TurtleWalk
2. Change the INSERT target from `quantized_walk_mint` to `walk_mint`
3. Change the write transport to DuckDB (WalkScribe reads DuckDB)
4. Ensure the schema columns align: TurtleWalk writes `(mode, regime_id, mu, sigma, p_jump, jump_mu, jump_sigma, tail_mult, confidence, pulse_type)` but `walk_mint` has `(ts, symbol, regime_id, mu, sigma, p_jump, confidence, mode, pulse_type)` — `jump_mu`, `jump_sigma`, `tail_mult` are not in the DuckDB schema and `ts`/`symbol` are missing from the write

This is more than a one-line fix — schema alignment and transport routing both need updating.
