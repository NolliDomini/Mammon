# Deep Dive: Fornix — Historical Memory Replay Engine

## 1. Purpose & Role
Fornix is **not** a live trade gate. It is the **historical replay engine** that feeds stored market bars through the real Mammon pipeline to mint full BrainFrame synapse tickets. These tickets ground the optimizer and DiamondGland to actual historical truth — not simulated data.

Named after the brain's fornix nerve bundle that carries memories from the hippocampus to the rest of the brain.

---

## 2. When Does It Run?
Fornix is a **batch process** — run manually or on a schedule, not in the live pulse loop. Typical use: overnight replay of all symbols in DuckPond to refresh synapse history before the next optimizer cycle.

Entry points:
- `Fornix.run(symbols, resume=True)` — main loop
- CLI: `python -m Hippocampus.fornix.service [--symbols] [--full] [--hours] [--no-resume]`

---

## 3. Inputs & Outputs

**Input:**
- `DuckPond.market_tape` — raw 1m OHLCV bars stored in DuckDB (`Hospital/Memory_care/duck.db`)
- `hormonal_vault.json` Gold params — used to configure the replay pipeline

**Output:**
- `DuckPond.history_synapse` — full BrainFrame snapshots (one per MINT pulse) written in batches of 100
- `Pituitary/diamond.json` — metadata from the post-replay DiamondGland search
- `hormonal_vault.json` updated `diamond_rails` bounds — safety rails for GP mutation

---

## 4. Control Flow

```
Fornix.run(symbols)
  → load symbol list from DuckPond
  → for each symbol:
      → check checkpoint (resume support)
      → load bars from DuckPond
      → _build_pipeline()          # fresh Soul + all lobes per symbol
      → chunk bars (500/chunk) → SmartGland.ingest() → pulses
      → for each pulse:
          → _route_pulse_through_soul()  # calls Soul._process_frame()
          → on MINT: buffer ticket (frame.to_synapse_dict())
          → flush buffer every 100 MINTs → DuckPond.write_synapse_batch()
          → checkpoint every N MINTs
  → _run_diamond()                 # DiamondGland.perform_deep_search()
  → _finalize_synapse_staging()    # Pineal archives/clears staging
```

---

## 5. Pipeline Construction (`_build_pipeline`)

Builds a **full Soul orchestration pipeline** per symbol, loaded with Gold params + test pulse config overrides:

| Lobe | Class |
|---|---|
| Right_Hemisphere | SnappingTurtle |
| Council | Council |
| Left_Hemisphere | TurtleMonte |
| Corpus | Callosum |
| Gatekeeper | Gatekeeper |
| Brain_Stem | Trigger |

`execution_mode = "BACKTEST"` — no real orders placed. All paths_per_lane scaled by test pulse config.

---

## 6. Test Pulse Configs

| Config | Monte Scale | Paths/Lane | Max Hours |
|---|---|---|---|
| `TEST_PULSE_25` | 0.25× | 2,500 | 8h |
| `TEST_PULSE_FULL` | 1.0× | 10,000 | 24h |

Default is `TEST_PULSE_25` — 25% fidelity for speed. Full fidelity used for production overnight runs.

---

## 7. DiamondGland Integration

After all symbols are processed, if `history_synapse` has ≥ 50 tickets:
- `DiamondGland.perform_deep_search()` runs Bayesian search on the accumulated data
- Outputs safety rails to `vault["diamond_rails"]["bounds"]`
- Returns `True` if consumed

Pineal then archives history_synapse and **wipes it only if Diamond consumed it**. If Diamond failed or had insufficient data, the staging is preserved for the next run.

---

## 8. Checkpoint / Resume

DuckPond stores per-symbol checkpoints (`fornix_checkpoint` table):
- `last_ts`, `bars_processed`, `mints_generated`
- On resume: bars before `last_ts` are skipped
- Checkpoint saved every `checkpoint_interval` MINTs (default: 1000)

---

## 9. Dependencies

| Dependency | Direction | Purpose |
|---|---|---|
| `DuckPond` | read/write | Bar source + synapse ticket storage |
| `SmartGland` | internal | 1m → 5m pulse generation |
| `Soul Orchestrator` | internal | Full pipeline per symbol |
| `DiamondGland` | outbound | Post-replay Bayesian rail search |
| `Pineal` | outbound | Finalize/archive/clear staging |
| `hormonal_vault.json` | read | Gold params for pipeline config |

---

## 10. Non-Obvious Behavior

- **Each symbol gets a fresh pipeline.** Soul, lobes, and SmartGland are all re-instantiated per symbol — no state bleeds between symbols.
- **Fornix calls `Soul._process_frame()` directly**, bypassing the Optical Tract entirely. There is no spray; the frame is passed directly.
- **`total_trades` counts `ready_to_fire` signals**, not actual fills. In BACKTEST mode Brain Stem logs to mock.
- **Progress callback hook** — `Fornix.__init__` accepts a `progress_callback` for dashboard wiring during live replay monitoring.
- **Time limit is wall-clock**, not bar count — if replay is slow and hits `max_hours`, remaining symbols are skipped. Checkpoints allow resuming on next run.

---

## 11. Open Questions / Risks

- **Fresh pipeline per symbol is expensive** — full lobe instantiation + vault load for each symbol. For large symbol lists this adds overhead.
- **No deduplication of synapse tickets between runs.** `write_synapse_batch` uses INSERT OR REPLACE on `machine_code` — safe, but if the same bars are replayed twice (after a failed Diamond run), tickets are overwritten with identical data.
- **Diamond threshold is hard-coded at 50 tickets** — a symbol with only 40 MINT pulses in history will never trigger Diamond even if the overall synapse count is large.
- **Test pulse paths_per_lane override** is applied at pipeline construction but Brain Stem's own Monte paths are separately configured via `risk_gate_paths_per_lane` and `valuation_paths` — all three must be overridden consistently or fidelity diverges.
