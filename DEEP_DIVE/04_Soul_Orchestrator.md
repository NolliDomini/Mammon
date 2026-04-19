# Deep Dive: Soul Orchestrator — The System Governor

## 1. Purpose & Role
Soul is the **brain's conductor**. It owns the Triple-Pulse lifecycle, sequences every lobe in deterministic order, builds and resets the BrainFrame each pulse, and is the only thing allowed to advance pulse state. Everything else reacts to what Soul hands it.

---

## 2. Inputs & Outputs

**Entry points:**
- `on_data_received(df)` — Optical Tract hook (primary live path); called by broadcast
- `pulse(symbols)` — direct call path; triggers Thalamus fetch then falls through to `_process_frame`
- `_process_frame(df)` — the actual engine; called by either above

**Output:**
- No return value — all effects are side effects on `BrainFrame` and downstream lobe calls
- `pulse_log` — list of per-pulse telemetry dicts (in-memory)

---

## 3. Key Data Structures

| Name | Purpose |
|---|---|
| `BrainFrame` | Single shared mutable object — all lobes read/write their slot by reference |
| `vault` | Loaded from `hormonal_vault.json` — Gold params are the live config source of truth |
| `lobes` | Dict of registered lobe instances keyed by name |
| `pending_entry` | Lives in Brain Stem, not Soul — Soul just calls Brain Stem |
| `last_action_ts` / `last_action_market_ts` | Timing anchors for MINT stale-guard |
| `pulse_log` | In-memory list of pulse telemetry dicts |

---

## 4. BrainFrame Anatomy

The frame is the **zero-copy shared state** object. Lobes mutate their designated slot directly — no copying, no message passing.

| Slot | Owner | Key Fields |
|---|---|---|
| `market` | Soul | `ohlcv`, `symbol`, `ts`, `pulse_type`, `execution_mode` |
| `structure` | Right Hemisphere | `price`, `active_hi`, `active_lo`, `gear`, `tier1_signal` |
| `risk` | Left Hemisphere | `mu`, `sigma`, `monte_score`, `regime_id`, `lane_survivals` |
| `environment` | Council | `confidence`, `atr`, `adx`, `volume_score`, `bid_ask_bps` |
| `valuation` | Brain Stem | `mean`, `std_dev`, `z_distance` |
| `execution` | PonsExecutionCost | `expected_slippage_bps`, `total_cost_bps` |
| `command` | Gatekeeper | `approved`, `ready_to_fire`, `sizing_mult`, `reason` |
| `standards` | Soul (vault) | Gold params dict — readable by all lobes |

`reset_pulse()` clears only ephemeral decision slots (`command`, `valuation`, `execution`, spread fields). Structure, risk, and environment are **preserved across pulses**.

---

## 5. Control Flow — `_process_frame(df)`

```
_process_frame(df)
  → frame.reset_pulse(pulse_type)      # clear ephemeral state
  → populate frame.market (ohlcv, ts, symbol, mode)
  → check trading_enabled_provider()   # trade gate (injected callable)
  → timing guard (MINT only):
      if elapsed since ACTION > max_market_delay → timing_inhibited = True
  → Right_Hemisphere.on_data_received() → fills frame.structure
  → Council.consult()                  → fills frame.environment
  → Left_Hemisphere.on_data_received() → fills frame.risk (fast pass)
  → walk_engine.build_seed()           → walk_seed for Monte
  → furnace.handle_frame()             → volume regime calibration
  → if tier1_signal == 1:
      ACTION:
        → Left_Hemisphere.simulate()   → full Monte → frame.risk
        → Corpus.score_tier()          → frame.risk.tier_score
        → Gatekeeper.decide()          → frame.command (approved, sizing)
        → if ready_to_fire AND can_trade:
            → Brain_Stem.load_and_hunt() → ARM pending entry
      SEED:
        → Left_Hemisphere.simulate()   → Monte at early window
  → MINT (always):
      → if timing_inhibited: frame.command.ready_to_fire = False
      → Brain_Stem.load_and_hunt()     → FIRE or CANCEL pending entry
  → amygdala.mint_synapse_ticket()     → persist frame snapshot
  → MINT only: pineal, vault_reload, crawler
  → pituitary every pulse
  → _log_pulse()
```

---

## 6. Dependencies

| Dependency | Direction | Purpose |
|---|---|---|
| `Optical Tract` | inbound | Triggers `on_data_received` on each spray |
| `Right_Hemisphere` | outbound | Structure analysis |
| `Council` | outbound | Environment scoring |
| `Left_Hemisphere` | outbound | Risk/Monte simulation |
| `Corpus` | outbound | Tier scoring |
| `Gatekeeper` | outbound | Final approval + sizing |
| `Brain_Stem` | outbound | Execution arm/fire |
| `Amygdala` | outbound | Frame persistence (synapse tickets) |
| `Pineal` | outbound | MINT-cycle memory secretion |
| `Pituitary` | outbound | Every-pulse hormone secretion |
| `VolumeFurnaceOrchestrator` | outbound | Regime/volume calibration |
| `QuantizedGeometricWalk` | outbound | Walk seed builder |
| `hormonal_vault.json` | inbound | Gold params (live config source of truth) |

---

## 7. State & Persistence

- `BrainFrame` — in-memory, reset each pulse (partially)
- `pulse_log` — in-memory only, not persisted
- `hormonal_vault.json` — re-read at every MINT via `_check_vault_mutation()` — hot-reload if Gold ID changed
- `Amygdala` writes synapse tickets to DuckDB at configured pulse types (default: MINT only)

---

## 8. Concurrency Model

Single-threaded pulse loop. `_process_frame` is synchronous — each lobe call blocks before the next starts. No async, no thread pool. The Optical Tract's synchronous fan-out means Soul blocks while it processes, which in turn blocks any subsequent spray subscribers.

---

## 9. Configuration (from hormonal_vault.json "gold" params)

Key params propagated to all lobes at `register_lobe()` and on hot-reload:

| Param | Effect |
|---|---|
| `active_gear` | Right Hemisphere gear selection |
| `monte_noise_scalar` | Left Hemisphere Monte noise |
| `monte_w_worst/neutral/best` | Left Hemisphere lane weights |
| `action_to_mint_max_market_sec` | MINT stale guard (default 90s) |
| `trading_enabled_provider` | Injected callable — runtime trade gate |

---

## 10. Failure Modes

- **Lobe exception**: `_run_lobe` catches, logs, then **re-raises** — a lobe failure aborts the rest of the cycle
- **Furnace failure**: caught and logged silently — does not abort cycle
- **Maintenance hook failures** (amygdala, pineal, pituitary, crawler, vault reload): each individually caught and logged — do not abort cycle
- **Timing inhibit**: MINT that arrives > 90s after ACTION has `ready_to_fire` forced to `False` before Brain Stem sees it — any pending entry is cancelled

---

## 11. Critical Functions

| Function | Why it matters |
|---|---|
| `_process_frame()` | The entire system in one function — sequencing is everything |
| `register_lobe()` | Wires a lobe in AND injects Gold params — registration order matters |
| `_check_vault_mutation()` | Hot-reload: detects Gold ID change and pushes new params to all lobes without restart |
| `reset_pulse()` (on BrainFrame) | Defines what persists vs. what is ephemeral across pulses |
| `generate_machine_code()` (on BrainFrame) | SHA-256 deterministic frame identity — used for dedup/audit |

---

## 12. Non-Obvious Behavior

- **`tier1_signal` is the master gate for full lobe engagement.** If Right Hemisphere does not set `tier1_signal = 1`, neither Left Hemisphere's full simulate, nor Corpus, nor Gatekeeper, nor Brain Stem ARM path are called at ACTION. The system sits quiet.
- **Lobe errors re-raise.** Unlike maintenance hooks, a failing core lobe (Right, Council, Left, Gatekeeper, Brain Stem) will bubble up and abort `_process_frame` entirely.
- **Gold params are the live config source of truth.** `hormonal_vault.json` is re-read at every MINT. Changing the Gold ID in the file triggers a hot-reload — no restart needed.
- **Double subscription guard**: if both Optical Tract and direct `pulse()` are wired, `_process_frame` would run twice per data event. Soul guards against this with the `if not self.optical_tract` check in `pulse()`.
- **`frame.standards` is a live dict reference** to vault gold params — lobes reading `frame.standards` always see current values after a hot-reload.

---

## 13. Open Questions / Risks

- **Lobe re-raise policy**: a single bad lobe (e.g. Right Hemisphere throwing on a malformed bar) kills the entire cycle — no partial processing.
- **`pulse_log` is unbounded in memory** — long-running sessions will grow this list indefinitely.
- **`BrainFrame` is shared mutable state with no locking** — if any async or threading were introduced, race conditions would be immediate.
- **timing inhibit monkeypatch**: the stale-MINT path directly sets `frame.command.ready_to_fire = False` mid-cycle — described in a comment as "a trick." It works, but it's fragile if the command slot is read before Brain Stem.
