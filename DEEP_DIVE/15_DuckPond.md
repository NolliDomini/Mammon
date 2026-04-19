# Deep Dive: DuckPond — Analytical Data Lake

## 1. Purpose & Role
DuckPond is the **analytical data lake** — an embedded DuckDB store that holds raw 1m bars, pre-calculated indicators, Fornix replay outputs, and long-lived BrainFrame archives. It is the primary persistent store for everything that flows into the optimizer and Fornix pipelines.

Named for the hippocampus's role in spatial memory and the duck-typing nature of DuckDB's columnar engine.

---

## 2. When Does It Run?

DuckPond is a **shared singleton** accessed by multiple components:

- **Thalamus** — `append_live_bars()` / `append_live_5m_bars()` every pulse
- **Fornix** — `get_bars_for_symbol()`, `write_synapse_batch()`, `save_checkpoint()` during replay
- **Pineal** — `archive_history_synapse()` + `clear_history_synapse()` post-Fornix
- **CLI** — standalone stats, prune, wipe operations

---

## 3. Schema — Six Tables

| Table | Purpose | Retention Default |
|---|---|---|
| `market_tape` | Raw 1m OHLCV bars (source of truth) | Disabled (0 = keep forever) |
| `market_tape_5m` | Live-aggregated 5m bars | Disabled |
| `cortex_precalc` | Pre-calculated ATR/bands/regime tags | Disabled |
| `history_synapse` | Fornix replay BrainFrame snapshots | 14 days |
| `fornix_checkpoint` | Per-symbol resume state | 30 days |
| `brainframe_mint_archive` | Long-lived MINT archive (post-Pineal) | Disabled |

---

## 4. Live Pipe Flow

```
Thalamus pulse
  → append_live_bars(df)          # 1m bars → market_tape (dedup on symbol+ts)
  → append_live_5m_bars(df)       # 5m bars → market_tape_5m (dedup on symbol+ts)
  → run_sunset(force=False)       # opportunistic pruning (respects min_interval)
```

---

## 5. Fornix Replay Flow

```
Fornix._run()
  → get_symbol_list()             # DISTINCT symbols from market_tape
  → get_bars_for_symbol(sym, after_ts)  # chronological 1m bars, resume-aware
  → [per 100 MINTs] write_synapse_batch(tickets)  # bulk INSERT history_synapse
  → save_checkpoint(sym, ts, bars, mints)
  → [post-replay, Pineal] archive_history_synapse(run_id)
  → clear_history_synapse()       # only if Diamond consumed
```

---

## 6. Sunset Policy

Policy-driven pruning is stored **in the DB itself** (`pond_settings` table), not in config files. Defaults:

| Setting | Default | Override Env Var |
|---|---|---|
| `market_tape_days` | 0 (disabled) | `MAMMON_SUNSET_MARKET_DAYS` |
| `history_synapse_days` | 14 | `MAMMON_SUNSET_HISTORY_DAYS` |
| `fornix_checkpoint_days` | 30 | `MAMMON_SUNSET_CHECKPOINT_DAYS` |
| `brainframe_archive_days` | 0 (disabled) | `MAMMON_SUNSET_ARCHIVE_DAYS` |
| `min_interval_minutes` | 720 (12h) | `MAMMON_SUNSET_INTERVAL_MINUTES` |

Sunset runs opportunistically — triggered by `append_live_bars`, `write_synapse_batch`, but throttled by `min_interval_minutes`.

---

## 7. Cortex Pre-Calculation

`calculate_cortex()` computes a set of windowed indicators across the full `market_tape` and writes to `cortex_precalc`. These are used by Fornix's pipeline (not the live Soul path directly):

- `atr_14` — avg(high-low) over 14 rows
- `mean_100` — 100-bar rolling mean
- `upper_band` — mean + 2σ (100-bar)
- `lower_band` — mean − 1.5σ (100-bar; asymmetric)
- `regime_tag` — 'HighVol' if current range > 2× 100-bar avg range, else 'Normal'

Note: the asymmetric band (2σ upper, 1.5σ lower) is intentional but undocumented.

---

## 8. Non-Obvious Behavior

- **Single persistent DuckDB connection per instance.** `duckdb.connect()` returns a connection tied to the file — no connection pooling. Concurrent access from multiple processes will deadlock (DuckDB file-level write lock).
- **Dedup is NOT idempotent under concurrent writes.** The `WHERE NOT EXISTS` check is not atomic — two simultaneous `append_live_bars` calls on the same bar can both pass the check and double-insert.
- **`MAMMON_DUCK_DB` env var overrides the default path.** Tests or parallel environments should always set this to a temp path or they'll corrupt the production lake.
- **Sunset is fire-and-forget.** Exceptions in `run_sunset()` are swallowed silently (`except Exception: print + return`). A broken sunset silently stops pruning.
- **`archive_history_synapse` does not deduplicate on the archive.** Calling it twice with the same data creates duplicate rows in `brainframe_mint_archive`.
- **`cortex_precalc` is never updated incrementally.** `calculate_cortex()` does `DELETE FROM cortex_precalc` then full recompute. On a large tape this is expensive and blocks all readers.
- **`history_synapse` has no unique constraint.** `write_synapse_batch` uses plain `INSERT`, not `INSERT OR REPLACE`. Rerunning Fornix without clearing staging will duplicate tickets.

---

## 9. Open Questions / Risks

- **Write contention.** If Thalamus and Fornix run concurrently (both calling DuckDB writes on the same file), one will block indefinitely — DuckDB's write-ahead lock is process-level.
- **Cortex precalc drift.** Live bars are appended to `market_tape` continuously but `cortex_precalc` is never auto-refreshed. Fornix uses `cortex_precalc` via `get_tape()`; if that table is stale, replay signal quality degrades.
- **`history_synapse` sunset vs Pineal.** Both the sunset policy (14-day rolling) and Pineal's `clear_history_synapse()` can delete from `history_synapse` independently. If sunset runs mid-replay and deletes in-progress staging, Fornix loses tickets without knowing.
