# Deep Dive: Thalamus — The Ingestion Lobe

## 1. Purpose & Role
Thalamus is the **sole entry point for market data**. It owns fetch → normalize → pulse-material generation. It is deliberately "dumb" — no indicators, no strategy, no execution. Its job is to hand clean, structured pulse-tuples to downstream lobes.

---

## 2. Inputs & Outputs

**Inputs:**
- Raw 1-minute OHLCV bars from:
  - Alpaca REST API (stock or crypto, via `StockHistoricalDataClient` / `CryptoHistoricalDataClient`)
  - DuckDB database (via `Librarian`, query on `master_test_key`)
  - Direct DataFrame injection via `drip_pulse()` ("Operation Drip Drip")

**Outputs:**
- `List[Tuple[str, pd.DataFrame]]` — each tuple is `(pulse_type, context_df)`
- `pulse_type` ∈ `{"SEED", "ACTION", "MINT"}`
- `context_df`: up to 50 trailing 5m aggregated bars + the current partial/complete bar, with `pulse_type` column appended
- Also sprays normalized bars via `optical_tract` (if wired) and writes to `duck_pond` (if wired)

---

## 3. Key Data Structures

| Name | Type | Purpose |
|---|---|---|
| `CANONICAL_COLS` | `list` | `["open","high","low","close","volume","symbol"]` — the schema law |
| `SmartGland.raw_list` | `List[tuple]` | Accumulates 1m bar tuples for the current 5m window |
| `SmartGland.context_df` | `pd.DataFrame` | Rolling 50-bar history of finalized 5m bars |
| `SmartGland.current_window_start` | `pd.Timestamp` | Tracks which 5m window is in-flight |
| `last_ingestion_event` | `dict` | Telemetry snapshot of most recent normalize call |

---

## 4. Control Flow

### `drip_pulse(raw_df)` — the live path
```
drip_pulse(raw_df)
  → _normalize_bars()             # strict schema enforcement, raises IngestionContractError on failure
  → duck_pond.append_live_bars()  # persist raw 1m bars (if connected)
  → gland.ingest(normalized)      # core Triple-Pulse resampling
      → for each 5m window boundary:
          emit MINT   (crossing into new window — finalizes previous)
          emit SEED   (once, at ≥2.25m elapsed)
          emit ACTION (once, at ≥4.5m elapsed)
  → _normalize_bars() on each agg_df
  → duck_pond.append_live_5m_bars() on MINT
  → optical_tract.spray() each pulse
```

### `pulse()` — the historical/batch path
Fetches from Alpaca or DB, normalizes, sprays raw bars via `optical_tract`. Does **not** run through SmartGland — returns raw normalized DataFrame, not pulse-tuples.

---

## 5. Dependencies

| Dependency | Direction | Purpose |
|---|---|---|
| `Hippocampus.Archivist.Librarian` | inbound | DB read for historical source |
| `optical_tract` | outbound (injected) | Spray normalized bars downstream |
| `duck_pond` | outbound (injected) | Persist raw 1m and finalized 5m bars |
| `alpaca` SDK | outbound | Fetch from Alpaca REST API |

Both `optical_tract` and `duck_pond` are optional — `None`-guarded throughout.

---

## 6. State & Persistence

- **In-memory state** lives in `SmartGland`: `raw_list`, `context_df`, `_seed_fired`, `_action_fired`, `current_window_start`
- State is **not persisted** — a restart loses the in-flight window
- Persistence is delegated outward: raw 1m bars → DuckPond, 5m finalized bars → DuckPond

---

## 7. Concurrency Model

No threading or async inside Thalamus itself. Processes blocks of bars synchronously. Cadence/sequencing authority sits with **Soul** (not Thalamus). Thalamus is called by whatever drives the pulse loop.

---

## 8. Configuration

| Param | Default | Effect |
|---|---|---|
| `window_minutes` | `5` | Size of aggregation window |
| `context_size` | `50` | Trailing bars kept in `context_df` |
| `seed_offset_min` | `2.25` | Minutes elapsed before SEED fires |
| `action_offset_min` | `4.5` | Minutes elapsed before ACTION fires |

All injected at construction. No env vars or config files read directly.

---

## 9. Failure Modes

- `IngestionContractError` raised (not silently swallowed) on: null input, invalid timestamps, missing OHLCV columns, negative volume, blank symbol
- SmartGland silently skips malformed payloads and increments `malformed_payloads_skipped` telemetry
- **Stale bar rule**: bars arriving for an already-finalized window are silently dropped (`continue`)
- If `optical_tract` or `duck_pond` are `None`, those side effects simply don't happen — no error

---

## 10. Critical Functions

| Function | Why it matters |
|---|---|
| `SmartGland.ingest()` | The entire pulse-generation engine — vectorized, stateful, boundary-aware |
| `Thalamus._normalize_bars()` | Schema contract enforcer — everything downstream trusts this output |
| `SmartGland._elapsed_minutes_for_marks()` | Shifts minute-aligned bar timestamps +1m before computing offsets, so 1m bars fire at correct 2.25/4.5 thresholds |
| `Thalamus.drip_pulse()` | Live-mode entry point — orchestrates normalize → persist → ingest → spray |
| `SmartGland._agg_window()` | Collapses raw 1m rows into a single 5m OHLCV bar |

---

## 11. Non-Obvious Behavior

- **MINT fires on window crossing, not on window close.** The previous window is finalized the moment a bar arrives with a later window floor — not at a clock tick.
- **SEED/ACTION are once-per-window.** Per-window boolean guards prevent duplicate pulses even if many bars arrive at once.
- **Context wrapping happens at emit time.** SEED and ACTION carry the trailing 50-bar context even though the window isn't closed yet.
- **`pulse()` does NOT produce pulse-tuples.** The historical fetch method bypasses SmartGland entirely. Only `drip_pulse()` produces Triple-Pulse output.
- **Minute-alignment shift**: the +1m adjustment in `_elapsed_minutes_for_marks` is a deliberate workaround for 1m bar open-time semantics — without it, a bar timestamped `HH:02:00` would only have 2.0m elapsed, never triggering the 2.25 threshold.

---

## 12. Open Questions / Risks

- **In-flight window loss on restart**: if the process dies mid-window, the partial `raw_list` is gone — that window's MINT will never fire.
- **`pulse()` vs `drip_pulse()` asymmetry**: two entry points with very different behavior, easy to wire the wrong one in a new consumer.
- **No backpressure**: if `optical_tract.spray()` is slow, `drip_pulse()` blocks. No queue or async handoff.
- **SmartGland is not thread-safe**: shared mutable state with no locks.
