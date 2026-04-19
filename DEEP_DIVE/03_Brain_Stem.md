# Deep Dive: Brain Stem — The Execution Edge

## 1. Purpose & Role
Brain Stem is the **final bridge to the broker**. It receives an approved `BrainFrame` from the Soul orchestrator, runs its own independent safety gates, and either arms → fires a BUY, holds, or exits an existing LONG position. It is the only lobe that touches real money.

---

## 2. Inputs & Outputs

**Input:**
- `load_and_hunt(pulse_type, frame, orchestrator, walk_engine, walk_seed)` — called each pulse
- `BrainFrame` — fully populated by upstream lobes before Brain Stem sees it
- `pulse_type` ∈ `{"SEED", "ACTION", "MINT"}`

**Output:**
- Side effects only: fires orders via Alpaca or mock adapter
- Updates `TreasuryGland` ledger (intents, fires, rejects, cancels)
- Returns `True` always

---

## 3. Key Data Structures

| Name | Purpose |
|---|---|
| `pending_entry` | Dict holding the armed intent from ACTION — survives until MINT fires or cancels it |
| `position` | Dict holding active LONG trade state (entry price, bands, symbol, z-score) |
| `last_execution_event` | Telemetry snapshot of most recent transition |
| `BrainFrame.command` | `ready_to_fire`, `approved`, `sizing_mult`, `notional` |
| `BrainFrame.risk` | `monte_score` — upstream Monte score |
| `BrainFrame.environment` | `atr`, `confidence`, `bid_ask_bps` |
| `BrainFrame.structure` | `price`, `mean` |

---

## 4. Control Flow

### ACTION pulse (entry evaluation)
```
load_and_hunt("ACTION", frame)
  → policy check: frame.command.approved == 1 and ready_to_fire
  → trading_enabled check (orchestrator gate)
  → payload validation (symbol, qty, price)
  → Gate 1: _run_risk_gate()     — Small Monte (999 paths), score >= gatekeeper_min_monte
  → Gate 2: _run_valuation_gate() — StdDev Monte (10k paths), entry z-score <= brain_stem_entry_max_z
  → Gate 3: prior > 0.5          — Blended conviction (turtle + council weights)
  → Gate 4: environment.confidence >= gatekeeper_min_council  (fail-safe only)
  → Guardrails: notional cap, max open positions, daily loss limit (via Treasury)
  → ALL pass → arm pending_entry, record intent in Treasury, mean_dev_monitor = ON
  → ANY fail → WAIT (no action)
```

### MINT pulse (deferred execution)
```
load_and_hunt("MINT", frame)
  → if pending_entry exists and no open position:
      → trading_enabled check
      → stale price guard (bps delta between armed_price and current price)
      → mean_dev check: z_score vs mean captured at ACTION — if price reverted, CANCEL
      → else: _fire_physical() → BUY
      → Treasury.fire_intent() records the fill
      → open position = set
  → clear pending_entry, mean_dev_monitor = OFF
```

### SEED pulse
Ignored for execution. Only updates `prev_price`.

### Exit logic (on ACTION/MINT with open position)
```
  → recalculate bands every pulse
  → price <= lower band  → STOP LOSS
  → price >= upper band  → TAKE PROFIT
  → z >= mean_rev_target_sigma AND price < prev_price → MEAN REVERSION exit
```

---

## 5. Dependencies

| Dependency | Direction | Purpose |
|---|---|---|
| `Medulla.treasury.gland.TreasuryGland` | outbound | Intent ledger — records every arm/fire/reject/cancel |
| `Medulla.orders.buy/sell` | outbound | Actual Alpaca order placement |
| `alpaca.trading.TradingClient` | outbound | Broker adapter (when mode = PAPER or LIVE) |
| `Cerebellum.Soul.brain_frame.BrainFrame` | inbound | Carries all upstream signals |
| `PonsExecutionCost` | sibling | Pre-trade cost estimate — writes to `frame.execution` |

---

## 6. State & Persistence

- `pending_entry`, `position`, `risk_score` — in-memory only, lost on restart
- All intent/fire/cancel transitions written to Treasury (DuckDB `money_orders` table)
- `last_execution_event` — in-memory telemetry only

---

## 7. Concurrency Model

- `_adapter_lock` (threading.Lock) guards `set_execution_mode()` — the only place the adapter is swapped at runtime
- `load_and_hunt()` itself has no locking — assumed to be called from a single pulse loop thread

---

## 8. Configuration (active defaults as of 2026-04-19)

| Param | Default | Effect |
|---|---|---|
| `execution_mode` | `DRY_RUN` | `DRY_RUN`/`BACKTEST` → mock; `PAPER`/`LIVE` → Alpaca |
| `gatekeeper_min_monte` | `0.30` | Gate 1 risk floor |
| `brain_stem_entry_max_z` | `0.8` | Gate 2 valuation cap |
| `gatekeeper_min_council` | `0.44` | Gate 4 environment fail-safe |
| `active_gear` | `3` | Scalper profile gear (set in Gold/Soul config) |
| `max_notional_per_order` | configured | Hard notional cap per trade |
| `max_open_positions` | configured | Position count cap (via Treasury) |
| `max_daily_realized_loss` | configured | Daily loss circuit breaker (via Treasury) |
| `brain_stem_stale_price_cancel_bps` | `0.0` | Cancel if price moved N bps between ACTION and MINT |
| `brain_stem_mean_dev_cancel_sigma` | `0.0` | Cancel if price reverted N sigma between ACTION and MINT |

---

## 9. Failure Modes

- **Treasury unavailable**: immediately rejects all ACTION entries — no trades without a ledger
- **Adapter rebind failure** (`set_execution_mode`): falls back silently to mock
- **Invalid payload** (bad symbol, zero qty, NaN price): logged to Treasury as REJECTED, no crash
- **Alpaca order failure**: `_fire_physical` catches exception, returns `status: error`, triggers REJECT path in Treasury
- **Stale price**: configurable bps guard cancels pending entry at MINT if price drifted too far

---

## 10. Critical Functions

| Function | Why it matters |
|---|---|
| `load_and_hunt()` | The entire engine — all entry, hold, exit, and ARM/FIRE logic |
| `_run_risk_gate()` | Gate 1: Small Monte (999 paths) biased by prior conviction |
| `_run_valuation_gate()` | Gate 2: 10k-path Monte, produces mean/sigma/bands used for z-score and exit levels |
| `_get_prior()` | Blended conviction = (monte_score × w_turtle) + (confidence × w_council) |
| `_fire_physical()` | The actual broker call — routes to Alpaca or mock |

---

## 11. Non-Obvious Behavior

- **ARM at ACTION, FIRE at MINT is a hard invariant.** No order is ever placed at ACTION. The 5-minute window boundary (MINT) is the execution gate.
- **Mean captured at ACTION, re-evaluated at MINT.** The z-score at MINT is computed against the ACTION-time mean — price reversion between pulses can cancel the trade even after full gate approval.
- **Prior injects directional bias into both Monte simulations.** A high conviction score literally tilts the simulated price distribution upward — conviction and risk are not independent.
- **Exit bands are recalculated every pulse**, not fixed at entry. This means the bands drift with ATR as the position ages.
- **LONG ONLY.** There is no short logic anywhere in Brain Stem.
- **`PonsExecutionCost.estimate()`** runs on ACTION, writes cost estimates to `frame.execution`, but Brain Stem's entry gates do not currently gate on `total_cost_bps` — it's informational.

---

## 12. Open Questions / Risks

- **Position state lost on restart**: an open position evaporates from memory — Brain Stem will not know it holds a live trade if the process restarts.
- **`frame.command.approved` check**: Brain Stem checks `approved == 1` but this field is set upstream (Soul/Medulla). If that approval logic has a bug, Brain Stem has no independent fallback beyond its own gates.
- **Exit band drift risk**: recalculating bands from a fresh Monte every pulse means exits can theoretically never trigger if ATR expands proportionally with price move.
- **No partial fill handling**: `_fire_physical` fires and forgets — no order status polling, no fill confirmation.

---

## Pons Execution Cost (sibling)

Pre-trade friction model, runs on ACTION only. Computes:
- `half_spread_bps` — from `frame.environment.bid_ask_bps`
- `impact_bps` — square-root market impact scaled by notional/avg_volume
- `vol_cost_bps` — ATR-relative volatility cost
- `total_cost_bps = slippage + fee`

Writes result to `frame.execution`. Falls back to 30bps fee if fee schedule missing, 100bps cap on error. Currently **informational only** — not gating execution.
