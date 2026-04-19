# Deep Dive: Dashboard — Flask Backend + V8 Titanium UI

## 1. Architecture Overview

The dashboard is two files:
- `dashboard.py` — Flask backend: engine lifecycle API, SSE stream, treasury KPI proxy, vault param proxy
- `dashboard/index.html` — Single-page frontend: TradingView chart, Brain Frame panels, control plane, log drawer

Static assets served from `dashboard/` via `send_from_directory`. API token injected into the HTML at serve time (`window.MAMMON_TOKEN`).

---

## 2. Layout — Every Bentobox

```
┌─────────────────────────────────────────────────────────────────────────────────┐
│  TOP BAR: MAMMON TITANIUM V8 | Pulse Dot | Pulse Type | Stale Timer            │
├──────────┬──────────────────────────────────────────────────┬───────────────────┤
│ LEFT     │              MAIN STAGE                          │ RIGHT             │
│ SIDEBAR  │  ┌──────────────────────────────────────────┐   │ SIDEBAR           │
│          │  │  5M TradingView Candlestick Chart        │   │ (Brain Frame)     │
│ Control  │  │  (Lightweight Charts, CDN)               │   │                   │
│ Plane    │  │                                          │   │ Pulse section     │
│          │  │  chartStatus overlay: INITIALIZING...    │   │ Structure section │
│ Start/   │  └──────────────────────────────────────────┘   │ Environment sect. │
│ Stop/    │                                                   │ Valuation section │
│ Refresh  │                                                   │ Execution section │
│          │                                                   │ Risk section      │
│ System   │                                                   │ Command section   │
│ Status   │                                                   │                   │
├──────────┴──────────────────────────────────────────────────┴───────────────────┤
│  BOTTOM BAR: Golden Params Strip                                                │
│  [ Strategy ] [ Monte ] [ Council ] [ Callosum ] [ Execution ]                 │
└─────────────────────────────────────────────────────────────────────────────────┘

  ← Hover left edge → LEFT NEXUS DRAWER (Vault KPIs: financial tray)
  ← Hover right edge → RIGHT NEXUS DRAWER (Neural Log)
```

---

## 3. Each Bentobox — Data Expected vs Data Actual

### 3.1 Top Bar
| Element | Source | Notes |
|---|---|---|
| `pulseDot` | SSE pulse event | Color: amber=SEED, blue=ACTION, green=MINT |
| `pulseText` | SSE `pulse_type` | SEED / ACTION / MINT / WAITING |
| `staleTimer` | Client-side setInterval(100ms) | Resets on each pulse; goes red at >15s |

**Status: Works correctly.** Stale timer is accurate. Color mapping is correct.

---

### 3.2 Left Sidebar — Control Plane
| Element | Data | Notes |
|---|---|---|
| Symbol input | User-typed | Default `BTC/USD` |
| START DRY RUN | POST `/api/start` | Injects `{mode: 'DRY_RUN', symbols: [symbol]}` |
| STOP ENGINE | POST `/api/stop` | Source: `ui`, reason: `manual_button` |
| REFRESH | Calls `refreshTreasury()` + `loadGoldenParams()` | Manual poll |
| System status text | `setStatus()` calls | String: READY / DRY_RUN_ACTIVE / STOPPED_* |

**Status: Works correctly.** Token auto-injected server-side at HTML render time.

---

### 3.3 Left Nexus Drawer — Vault KPIs (THE BROKEN TRAY)

Populated by `refreshTreasury()` → GET `/api/treasury/status` → `TreasuryGland.get_status()`, polled every 5 seconds while engine runs.

**What the frontend expects vs what the backend returns:**

| UI Element | JS reads | Backend key | Backend value | What renders |
|---|---|---|---|---|
| Orders | `d.orders` | `orders` | `{armed:N, fired:N, ...}` **dict** | `[object Object]` |
| Fills | `d.fills` | *(missing)* | not returned | always `0` |
| Positions | `d.positions` | `open_positions` | integer | always `0` (wrong key) |
| Net PnL | `d.net_pnl` | `realized_pnl` | float | always `$0.00` (wrong key) |
| Drawdown | `d.drawdown` | *(missing)* | not returned | always `$0.00` |
| Win Rate | `d.win_rate` | *(missing)* | not returned | always `0.0%` |

**All six fields are broken.** The field name contract between frontend and backend does not match anywhere.

**Root cause 1 — API response shape mismatch:**
`TreasuryGland.get_status()` returns:
```python
{
    "mode": "DRY_RUN",
    "open_positions": 0,        # frontend reads "positions"
    "orders": {                 # frontend reads this as a number
        "armed": 0, "fired": 0, "canceled": 0,
        "partial": 0, "rejected": 0, "timeout": 0
    },
    "realized_pnl": 0.0,        # frontend reads "net_pnl"
    "unrealized_pnl": 0.0,      # frontend ignores entirely
    "source": "sim",
}
```

The frontend was written expecting a flat schema (`orders`, `fills`, `positions`, `net_pnl`, `drawdown`, `win_rate`). The backend returns a nested schema with different key names and no `fills`, `drawdown`, or `win_rate` fields at all.

**Root cause 2 — TreasuryGland uses SQLite shim, not TimescaleDB:**
`TreasuryGland.__init__` does `self.librarian = librarian or Librarian()` — it instantiates the `Librarian` SQLite shim, not `MultiTransportLibrarian`. The treasury tables (`money_orders`, `money_positions`, etc.) are created in and read from SQLite at `Path.cwd() / runtime / .tmp_test_local / compat_librarian.db`.

**Root cause 3 — Dashboard creates a fresh TreasuryGland per request:**
`api_treasury_status()` does:
```python
treasury = TreasuryGland(mode=state.mode)
status = treasury.get_status()
```

This creates a new `Librarian` → new SQLite connection per API call. As long as Brain Stem's `TreasuryGland` uses the same CWD-relative SQLite path, this is consistent. But it means every GET `/api/treasury/status` opens and closes a SQLite connection.

**Root cause 4 — The error fallback masks the breakage:**
```python
except Exception as e:
    return jsonify({
        "orders": 0, "fills": 0, "positions": 0,
        "net_pnl": 0.0, "drawdown": 0.0, "win_rate": 0.0,
        "error": _safe_str(e, 100),
    })
```

If TreasuryGland fails (missing tables, locked SQLite), the fallback returns the *flat schema* the frontend expects — but with all zeros. This means: if TreasuryGland is healthy and returns data, the frontend shows `[object Object]`; if it crashes, the frontend shows correct-looking zeros. The error path accidentally has the right shape.

**Fix (minimal):** Flatten the API response in `api_treasury_status()`:
```python
status = treasury.get_status()
orders_dict = status.get("orders", {})
return jsonify({
    "orders": orders_dict.get("fired", 0) + orders_dict.get("partial", 0),
    "fills": orders_dict.get("fired", 0),
    "positions": status.get("open_positions", 0),
    "net_pnl": status.get("realized_pnl", 0.0) + status.get("unrealized_pnl", 0.0),
    "drawdown": 0.0,    # not yet computed
    "win_rate": 0.0,    # not yet computed
})
```

---

### 3.4 Main Stage — Candlestick Chart
| Element | Source | Notes |
|---|---|---|
| Candles | SSE `pulse` event `bar_*` fields | `bar_time`, `bar_open/high/low/close` |
| Chart init | `initChart()` on engine start | TradingView Lightweight Charts 4.2.1 via CDN |
| Resize | ResizeObserver | Responds to container size changes |

**Status: Works IF bars arrive from Thalamus.** Chart is not pre-populated from history on page load. On reconnect after browser refresh, the chart starts empty — no historical bars fetched.

**One issue:** Wall-clock MINT events (triggered when no new bar arrives) call `_frame_to_event()` without a `bar_dict`. These events have `pulse_type=MINT` but no `bar_*` fields. `updateCandle()` checks `if (!candleSeries || !d.bar_time) return` — so wall-clock MINTs correctly do not update the chart but also don't show any data.

**CDN dependency:** `https://unpkg.com/lightweight-charts@4.2.1/dist/...` — chart fails completely with no internet. No offline fallback, no local copy.

---

### 3.5 Right Sidebar — Brain Frame

7 sections populated by `applyPulse(d)` from SSE `pulse` events. Every field maps from `_frame_to_event()` in the backend.

**Section-by-section mapping:**

**Pulse section:**
| UI | Event field | Source in pipeline |
|---|---|---|
| Pulse | `pulse_type` | SmartGland pulse type |
| Symbol | `symbol` | Thalamus |
| Price | `price` | `frame.structure.price` |
| Mode | `mode` | Engine state |
| Reason | `reason` | `frame.command.reason` |
| Total | `council + monte + tier` scores summed | Computed client-side |

**Structure section:**
| UI | Event field | Source |
|---|---|---|
| Tier1 | `tier1_signal` | SnappingTurtle Donchian breakout |
| Gear | `gear` | Gold param `active_gear` |
| Hi | `active_hi` | Donchian high (prev bar) |
| Lo | `active_lo` | Donchian low (prev bar) |

**Environment section:**
| UI | Event field | Source |
|---|---|---|
| Council | `council_score` | Council confidence blend |
| ATR | `atr` | Council SpreadEngine |
| Spread | `bid_ask_bps` | SpreadEngine bid/ask |
| Regime | `spread_regime` | SpreadEngine regime tag |
| ADX | `adx` | Council |
| Vol | `volume_score` | Council volume sub-score |

**Valuation section:**
| UI | Event field | Source |
|---|---|---|
| Mean | `val_mean` | `frame.valuation.mean` |
| Z-Dist | `val_z_distance` | `frame.valuation.z_distance` |
| Spread | `spread_score` | `frame.environment.spread_score` |

**Status: Valuation section may show zeros.** `frame.valuation` is a BrainFrame slot. Whether it is populated depends on whether a Valuation lobe is registered. In the current `_engine_loop`, no Valuation lobe is registered — `Right_Hemisphere`, `Council`, `Left_Hemisphere`, `Corpus`, `Gatekeeper`, `Brain_Stem`, `Thalamus` are registered. No explicit Valuation lobe. `val_mean`, `val_std_dev`, `val_z_distance` will be 0 unless Brain Stem or another lobe writes to `frame.valuation`.

**Execution section:**
| UI | Event field | Source |
|---|---|---|
| Slip | `exec_expected_slippage_bps` | `frame.execution.expected_slippage_bps` |
| Cost | `exec_total_cost_bps` | `frame.execution.total_cost_bps` |

**Status: May show zeros.** Same issue — no explicit Execution lobe registered. PonsExecutionCost is documented as informational only (not modifying BrainFrame). These slots are populated by Brain Stem's cost model if wired.

**Risk section:**
| UI | Event field | Source |
|---|---|---|
| Monte | `monte_score` | TurtleMonte weighted survival |
| Tier | `tier_score` | Callosum blend |
| Regime | `regime_id` | TurtleWalk D_A_V_T string |
| Worst | `worst_survival` | TurtleMonte worst lane |
| Neutral | `neutral_survival` | TurtleMonte neutral lane |
| Best | `best_survival` | TurtleMonte best lane |

**Status: Works correctly** when Monte Carlo completes.

**Command section:**
| UI | Event field | Source |
|---|---|---|
| Apprv | `approved` | Gatekeeper (ACTION pulse gate) |
| Ready | `ready_to_fire` | Brain Stem ARM/FIRE |
| Qty | `qty` | `frame.command.qty` |
| Notional | `notional` | `frame.command.notional` |
| Convict | `cost_adjusted_conviction` | `frame.command.cost_adjusted_conviction` |
| Risk% | `risk_used` | `frame.command.risk_used` |
| Size Reason | `size_reason` | `frame.command.size_reason` |

**Status: Qty/Notional/Conviction/Risk% likely zeros.** These fields require the full Brain Stem sizing model (`risk_per_trade_pct`, `equity` params, cost penalty) to be wired. In DRY_RUN they may be computed but not persisted to BrainFrame command slot correctly if Brain Stem skips sizing in dry run.

---

### 3.6 Right Nexus Drawer — Neural Log
Append-only log, max 200 entries, auto-scrolls. Populated by:
- Every `pulse` SSE event → `MINT | BTC/USD | $65432.10 | APPROVED | BREAKOUT`
- `engine` lifecycle events
- `error` events
- `system` events
- `furnace` events (Hospital optimizer activation, if wired)

**Status: Works correctly.** Oldest entries evicted when > 200. Timestamps are client-side (`HH:MM:SS`).

---

### 3.7 Bottom Bar — Golden Params Strip

Populated once by `loadGoldenParams()` → GET `/api/vault/gold` → Redis via `librarian.get_hormonal_vault()`.

**Param mapping:**
| UI Label | Param key | Group |
|---|---|---|
| Gear | `active_gear` | Strategy |
| GK M. | `gatekeeper_min_monte` | Strategy |
| Stop | `stop_loss_mult` | Strategy |
| BkEvn | `breakeven_mult` | Strategy |
| Noise | `monte_noise_scalar` | Monte |
| W Wrst/Neut/Best | `monte_w_worst/neutral/best` | Monte |
| W ATR/ADX/Vol/VWAP | `council_w_*` | Council |
| W Monte/Right/Weak | `callosum_w_*` | Callosum |
| F Mak/Tak | `fee_maker_bps/fee_taker_bps` | Execution |
| S Max | `max_slippage_bps` | Execution |
| Risk% | `risk_per_trade_pct` | Execution |
| Eqty | `equity` | Execution |

**Status: Partial.** Populated once on engine start and on manual REFRESH. Not live-updated when Pituitary crowns a new Gold mid-session. The strip shows the Gold params at start time — if GP mutation runs and changes Gold, the strip goes stale.

**Note:** The Execution group params (`fee_maker_bps`, `fee_taker_bps`, `max_slippage_bps`, `risk_per_trade_pct`, `equity`) are in the librarian's 47-key PARAM_KEYS but not in Pituitary's 23-key list — they may not be present in the Gold params dict at all, leaving those cells as `-`.

`callosum_w_adx` is in the Gold params and in the Callosum group per the code, but is **not shown** in the bottom bar — the Callosum group only shows `W Monte`, `W Right`, `W Weak`. `callosum_w_adx` is missing from the UI.

---

## 4. Engine Loop — Key Behaviors

### Wall-Clock MINT vs Bar-Triggered MINT (Deduplication)
The engine runs two MINT triggers:
1. **Wall-clock** (`current_window_start > last_wallclock_window_start`) — fires when the system clock crosses a 5-minute boundary, using the current BrainFrame state
2. **Bar-triggered** — fires when Thalamus returns a new bar that produces a MINT pulse

Dedup guard:
```python
if pulse_type == "MINT":
    minted_window_start = this_bar_window - 300
    if last_wallclock_mint_window_start is not None and minted_window_start == last_wallclock_mint_window_start:
        continue  # skip — wall-clock already covered this window
```

**Issue:** Wall-clock MINT fires using **stale BrainFrame state** (from the last bar processed). If no new bar arrived before the 5-minute boundary, the MINT event reflects the previous bar's pipeline state — `active_hi`, `active_lo`, `monte_score` are all from the last bar. This is architecturally correct (you MINT what you have) but the dashboard doesn't indicate it's a stale-frame MINT vs a fresh-bar MINT.

### 5-Minute Boundary Sync
On engine start, the loop waits until `ceil(now / 300) * 300` before entering the poll loop. This is correct — it ensures the first pulse aligns to a real 5-minute boundary. The wait can be up to 5 minutes.

### Poll Interval
`poll_interval_sec = 0.5` — polls Alpaca every 500ms. For a 5-minute bar system this is 600 polls per bar, most returning no new data.

---

## 5. Health Logs — Engine Lifecycle

Lifecycle events written to `runtime/logs/engine_lifecycle.jsonl`:
- `ENGINE_START_REQUESTED` — API `/api/start` called
- `ENGINE_STARTED` — engine thread initialized successfully
- `ENGINE_STOP_REQUESTED` — API `/api/stop` called
- `ENGINE_EXIT` — thread terminated (normal, crash, or unexpected)

`ENGINE_EXIT` includes: `exit_kind` (CRASH / STOP_REQUESTED / UNEXPECTED_STOP), `exit_source`, `exit_reason`, `exit_detail`, `duration_sec`, `had_crash`.

GET `/api/engine/lifecycle?limit=100` returns the tail of this file as JSON.

**On dashboard load**, `hydrateFromCurrentState()` reads `/api/state` and surfaces the last exit kind + crash detail in the Neural Log. If the engine crashed, the last crash message and exception type are shown on reconnect.

---

## 6. Auth & Security

- Bearer token required on all `/api/*` routes
- Token injected into HTML at serve time (`window.MAMMON_TOKEN`) — never stored client-side in localStorage
- LIVE mode requires an additional one-time unlock token (`/api/mode/live-unlock/arm` → `api_start` with matching token)
- Kill switch: trip sets `mode=LOCKED`, `trading_enabled=False` on both EngineState and live Orchestrator/Trigger instances
- `STOP_ON_WINDOW_CLOSE` env flag: uses `navigator.sendBeacon` on `beforeunload` — only works for GET; the stop URL uses query param auth (`?token=`)

---

## 7. Non-Obvious Behavior

- **`_require_infra()` blocks start.** `/api/start` calls `_require_infra()` which pings Redis AND TimescaleDB. If either is down, engine won't start even in DRY_RUN mode. This is intentional but means DRY_RUN has the same infra requirements as LIVE.
- **`furnace` attribute on orchestrator.** `_publish_furnace_run_events()` calls `getattr(orchestrator, "furnace", None)` — if Hospital's VolumeFurnace is not attached to the orchestrator, this is always None and furnace events never appear in the log.
- **`/_shutdown` route uses `werkzeug.server.shutdown`.** In production (non-dev WSGI), `werkzeug.server.shutdown` is None — falls back to `os._exit(0)` in a background thread. Hard kill, no graceful shutdown.
- **SSE stream never closes.** The `generate()` function is an infinite loop with a 30-second timeout for keepalive. The connection stays open until the browser closes it or the server dies. There is no per-client timeout.
- **Chart not hydrated on reconnect.** `hydrateFromCurrentState()` attaches SSE if engine is running but does not call `/api/frame/latest` to pre-populate the chart. First candle appears only on the next pulse.
- **`api_frame_latest` exists but is never used by the UI.** The poll fallback endpoint at `/api/frame/latest` is defined but `hydrateFromCurrentState()` doesn't call it — the chart hydration gap on reconnect is a known unfinished path.

---

## 8. Open Questions / Risks

- **Left financial tray broken** — all 6 fields wrong (see §3.3). Fix is 10 lines in `api_treasury_status()`.
- **TreasuryGland fresh-instantiated per request** — opens a SQLite file every 5 seconds. At scale this is fine, but the CWD-relative path assumption means running the dashboard from a different directory breaks treasury reads silently (wrong SQLite file, tables exist but are empty).
- **No `drawdown` or `win_rate` computation exists anywhere.** Not in TreasuryGland, not in any other service. These fields would require post-trade aggregation logic that hasn't been written.
- **Gold params strip goes stale.** Pituitary GP mutation runs every 4th MINT (~20 minutes live). If the dashboard session is long, the bottom bar drifts from the active Gold. A vault hash or ID change check could trigger a strip refresh.
- **`callosum_w_adx` not shown in Callosum group.** The strip shows W Monte, W Right, W Weak but omits W ADX — it's a 4-weight group with one weight missing from the display.
- **DRY_RUN requires Redis + TimescaleDB.** `_require_infra()` fails hard on missing connections regardless of mode. Truly offline DRY_RUN is not possible without mocking those connections.

---

## 9. Full Parameter Trace — Every Field, Every Box

Second-pass audit. Every parameter traced from backend source → `_frame_to_event()` → SSE event key → `applyPulse(d)` JS read → DOM element.

Legend: ✅ works | ⚠️ works but with caveat | ❌ broken/always wrong | ➖ always zero (no writer)

---

### 9.1 Top Bar

| DOM id | JS source | Backend | Status |
|---|---|---|---|
| `pulseDot` | `triggerPulse(d.pulse_type)` | `pulse_type` in SSE event | ✅ |
| `pulseText` | `triggerPulse(d.pulse_type)` | `pulse_type` | ✅ |
| `staleTimer` | `setInterval(100ms)` increments `timeSincePulse` | client-side only | ✅ |
| `connectionState` | `setStatus()` on SSE / API callbacks | client-side string | ✅ |

---

### 9.2 Left Sidebar — Control Plane

| DOM id / button | JS action | Backend route | Status |
|---|---|---|---|
| `dryRunSymbol` | user input, default `BTC/USD` | sent to `/api/start` | ✅ |
| START DRY RUN | POST `/api/start` `{mode:'DRY_RUN', symbols:[symbol]}` | `api_start()` | ✅ |
| STOP ENGINE | POST `/api/stop` `{source:'ui', reason:'manual_button'}` | `api_stop()` | ✅ |
| REFRESH | `refreshTreasury()` + `loadGoldenParams()` | both API calls | ✅ |

---

### 9.3 Left Nexus — Vault KPIs

Polled every 5s via `refreshTreasury()` → GET `/api/treasury/status`.

`TreasuryGland.get_status()` actual return keys vs what JS reads:

| DOM id | JS reads | Actual key in response | Actual type | Renders |
|---|---|---|---|---|
| `dryOrders` | `d.orders` | `"orders"` | **dict** `{armed,fired,...}` | `[object Object]` ❌ |
| `dryFills` | `d.fills` | *(absent)* | — | `0` ❌ |
| `dryPositions` | `d.positions` | `"open_positions"` | int | `0` (wrong key) ❌ |
| `dryNetPnl` | `d.net_pnl` | `"realized_pnl"` + `"unrealized_pnl"` | floats | `$0.00` (wrong key) ❌ |
| `dryDrawdown` | `d.drawdown` | *(absent, never computed)* | — | `$0.00` ❌ |
| `dryWinRate` | `d.win_rate` | *(absent, never computed)* | — | `0.0%` ❌ |

**All 6 fields broken.** When TreasuryGland throws an exception, the error fallback accidentally uses the flat schema the frontend expects — so zeros on a crash look correct while real data looks broken.

---

### 9.4 Main Stage — Chart

| JS field read | Backend source | Status |
|---|---|---|
| `d.bar_time` | `int(bar_ts.timestamp())` | ✅ — present only on bar-triggered pulses, absent on wall-clock MINTs |
| `d.bar_open/high/low/close` | `raw_df.iloc[0][...]` | ✅ |
| `d.bar_volume` | `raw_df.iloc[0]["volume"]` | injected but never read by chart (TradingView candleSeries doesn't use volume) — silent |

**Chart on reconnect:** `hydrateFromCurrentState()` reattaches SSE but does NOT call `/api/frame/latest`. Chart starts empty on every browser refresh. ⚠️

---

### 9.5 Right Sidebar — Brain Frame, Full Field Trace

Backend function: `_frame_to_event(frame, symbol, pulse_type, mode, bar_dict)`.
BrainFrame is always initialized (`BrainFrame.__init__()` sets all slots to zero defaults). Slots are populated by registered lobes only.

**Lobes registered in `_engine_loop`:** SnappingTurtle, Council, TurtleMonte, Callosum, Gatekeeper, Trigger(BrainStem), Thalamus.
**Lobes NOT registered:** AllocationGland, PonsExecutionCost, any Valuation lobe.

#### Pulse Section

| DOM id | JS reads | Event key | Backend expression | Writer lobe | Status |
|---|---|---|---|---|---|
| `bfCurrentPulse` | `d.pulse_type` | `pulse_type` | arg passed to `_frame_to_event` | SmartGland via Thalamus | ✅ |
| `bfSymbol` | `d.symbol` | `symbol` | arg passed in | Thalamus | ✅ |
| `bfPrice` | `d.price` | `price` | `frame.structure.price` | SnappingTurtle | ✅ |
| `bfMode` | `d.mode` | `mode` | arg passed in | EngineState | ✅ |
| `bfReason` | `d.reason` | `reason` | `frame.command.reason` | Gatekeeper → BrainStem | ✅ |
| `bfTotal` | `council + monte + tier` sum | computed client-side | — | — | ✅ |

#### Structure Section

| DOM id | JS reads | Event key | Backend expression | Status |
|---|---|---|---|---|
| `bfTier1` | `d.tier1_signal` | `tier1_signal` | `frame.structure.tier1_signal` → SnappingTurtle | ✅ |
| `bfGear` | `d.gear` | `gear` | `frame.structure.gear` → SnappingTurtle | ✅ |
| `bfHi` | `d.active_hi` | `active_hi` | `frame.structure.active_hi` → SnappingTurtle | ✅ |
| `bfLo` | `d.active_lo` | `active_lo` | `frame.structure.active_lo` → SnappingTurtle | ✅ |

#### Environment Section

| DOM id | JS reads | Event key | Backend expression | Status |
|---|---|---|---|---|
| `bfCouncil` | `d.council_score` | `council_score` | `frame.environment.confidence` | ✅ — `confidence` is the Council field name; mapping is correct |
| `bfAtr` | `d.atr` | `atr` | `frame.environment.atr` → Council/SpreadEngine | ✅ |
| `bfBidAsk` (labeled "Spread") | `d.bid_ask_bps` | `bid_ask_bps` | `frame.environment.bid_ask_bps` → SpreadEngine | ✅ if SpreadEngine has real quotes; otherwise ATR fallback value |
| `bfSpreadRegime` (labeled "Regime") | `d.spread_regime` | `spread_regime` | `frame.environment.spread_regime` | ✅ |
| `bfAdx` | `d.adx` | `adx` | `frame.environment.adx` → Council | ✅ |
| `bfVol` | `d.volume_score` | `volume_score` | `frame.environment.volume_score` → Council | ✅ |

#### Valuation Section

`ValuationSlot` exists on BrainFrame but **no Valuation lobe is registered in `_engine_loop`**. It resets to zero on every `frame.reset_pulse()`. No lobe writes to it.

| DOM id | JS reads | Event key | Backend expression | Status |
|---|---|---|---|---|
| `bfMean` | `d.val_mean` | `val_mean` | `frame.valuation.mean` | ➖ always 0.00 |
| `bfZDist` | `d.val_z_distance` | `val_z_distance` | `frame.valuation.z_distance` | ➖ always 0.0000 |
| `bfSpreadScore` (labeled "Spread") | `d.spread_score` | `spread_score` | `frame.environment.spread_score` | ✅ — reads from environment, not valuation; confusingly labeled but gets data |

Note: There are **two cells labeled "Spread"** in different sections — one in Environment (`bid_ask_bps`) and one in Valuation (`spread_score` from environment). Different metrics, same label.

#### Execution Section

`ExecutionSlot` exists on BrainFrame but resets to zero on every `reset_pulse()`. PonsExecutionCost is documented as informational only and is not registered in `_engine_loop`.

| DOM id | JS reads | Event key | Backend expression | Status |
|---|---|---|---|---|
| `bfSlippage` | `d.exec_expected_slippage_bps` | `exec_expected_slippage_bps` | `frame.execution.expected_slippage_bps` | ➖ always 0.00 |
| `bfCost` | `d.exec_total_cost_bps` | `exec_total_cost_bps` | `frame.execution.total_cost_bps` | ➖ always 0.00 |

#### Risk Section

| DOM id | JS reads | Event key | Backend expression | Status |
|---|---|---|---|---|
| `bfMonte` | `d.monte_score` | `monte_score` | `frame.risk.monte_score` → TurtleMonte | ✅ |
| `bfTier` | `d.tier_score` | `tier_score` | `frame.risk.tier_score` → Callosum | ✅ |
| `bfRegime` | `d.regime_id` | `regime_id` | `frame.risk.regime_id` → TurtleWalk | ✅ |
| `bfWorst` | `d.worst_survival` | `worst_survival` | `frame.risk.worst_survival` → TurtleMonte | ✅ |
| `bfNeutral` | `d.neutral_survival` | `neutral_survival` | `frame.risk.neutral_survival` → TurtleMonte | ✅ |
| `bfBest` | `d.best_survival` | `best_survival` | `frame.risk.best_survival` → TurtleMonte | ✅ |

#### Command Section

`AllocationGland` writes `qty`, `notional`, `size_reason`, `risk_used`, `cost_adjusted_conviction` to `frame.command`. **AllocationGland is NOT registered as a lobe in `_engine_loop`** — it is a standalone class. Whether Trigger (BrainStem) calls it internally is unclear from the engine registration code. If not called, all five sizing fields remain at BrainFrame defaults.

| DOM id | JS reads | Event key | Backend expression | Status |
|---|---|---|---|---|
| `bfApproved` | `d.approved` | `approved` | `frame.command.approved` → Gatekeeper | ✅ |
| `bfReady` | `d.ready_to_fire` | `ready_to_fire` | `frame.command.ready_to_fire` → BrainStem ARM | ✅ |
| `bfQty` | `d.qty` | `qty` | `frame.command.qty` → AllocationGland | ⚠️ 0 if AllocationGland not called |
| `bfNotional` | `d.notional` | `notional` | `frame.command.notional` → AllocationGland | ⚠️ 0 if AllocationGland not called |
| `bfConviction` | `d.cost_adjusted_conviction` | `cost_adjusted_conviction` | `frame.command.cost_adjusted_conviction` → AllocationGland | ⚠️ 0 if AllocationGland not called |
| `bfRiskUsed` | `d.risk_used` | `risk_used` | `frame.command.risk_used` → AllocationGland | ⚠️ 0 if AllocationGland not called |
| `bfSizingReason` | `d.size_reason` | `size_reason` | `frame.command.size_reason` → AllocationGland | ⚠️ `"NONE"` if AllocationGland not called |

---

### 9.6 Bottom Bar — Golden Params Strip

`loadGoldenParams()` → GET `/api/vault/gold` → `vault["gold"]["params"]`.

Pituitary's canonical `PARAM_KEYS` has 23 params. The dashboard maps 20 params across 5 groups. Cross-reference:

| UI Label | Param key | In PARAM_KEYS? | In UI? |
|---|---|---|---|
| Gear | `active_gear` | ✅ | ✅ |
| GK M. | `gatekeeper_min_monte` | ✅ | ✅ |
| *(no cell)* | `gatekeeper_min_council` | ✅ | ❌ **missing** |
| Stop | `stop_loss_mult` | ✅ | ✅ |
| BkEvn | `breakeven_mult` | ✅ | ✅ |
| Noise | `monte_noise_scalar` | ✅ | ✅ |
| W Wrst | `monte_w_worst` | ✅ | ✅ |
| W Neut | `monte_w_neutral` | ✅ | ✅ |
| W Best | `monte_w_best` | ✅ | ✅ |
| W ATR | `council_w_atr` | ✅ | ✅ |
| W ADX | `council_w_adx` | ✅ | ✅ |
| W Vol | `council_w_vol` | ✅ | ✅ |
| W VWAP | `council_w_vwap` | ✅ | ✅ |
| W Monte | `callosum_w_monte` | ✅ | ✅ |
| W Right | `callosum_w_right` | ✅ | ✅ |
| *(no cell)* | `callosum_w_adx` | ✅ | ❌ **missing** |
| W Weak | `callosum_w_weak` | ✅ | ✅ |
| *(no cell)* | `brain_stem_w_turtle` | ✅ | ❌ **missing** |
| *(no cell)* | `brain_stem_w_council` | ✅ | ❌ **missing** |
| *(no cell)* | `brain_stem_survival` | ✅ | ❌ **missing** |
| *(no cell)* | `brain_stem_noise` | ✅ | ❌ **missing** |
| *(no cell)* | `brain_stem_sigma` | ✅ | ❌ **missing** |
| *(no cell)* | `brain_stem_bias` | ✅ | ❌ **missing** |
| F Mak | `fee_maker_bps` | ❌ not in PARAM_KEYS | cell exists → shows `-` |
| F Tak | `fee_taker_bps` | ❌ not in PARAM_KEYS | cell exists → shows `-` |
| S Max | `max_slippage_bps` | ❌ not in PARAM_KEYS | cell exists → shows `-` |
| Risk% | `risk_per_trade_pct` | ❌ not in PARAM_KEYS | cell exists → shows `-` |
| Eqty | `equity` | ❌ not in PARAM_KEYS | cell exists → shows `-` |

**Summary:** 8 of 23 PARAM_KEYS have no UI cell (Brain Stem group entirely absent from the strip). 5 cells exist for params that are not in Gold PARAM_KEYS — they will always show `-` (JS check `map[label.textContent] !== undefined` skips them). The entire BrainStem sub-system (`brain_stem_w_turtle`, `brain_stem_w_council`, `brain_stem_survival`, `brain_stem_noise`, `brain_stem_sigma`, `brain_stem_bias`) has no representation in the bottom bar.

Also: strip is loaded once at start. Every 4th MINT (~20 min) Pituitary may crown new Gold — the strip goes stale silently.

---

## 10. MNER — Mammon Neural Error Registry

**MNER** = Mammon Neural Error Registry. Every structured failure in the codebase is tagged with a code following the format:

```
[LOBE]-[LEVEL]-[PIECE]-[ID]
```

- `LOBE` — module abbreviation (PONS, COUNCIL, ALLOC, PITU, HIPP, MNER...)
- `LEVEL` — severity (`E` = error, `W` = warning implied)
- `PIECE` — implementation piece number
- `ID` — numeric error ID within that piece

Examples from the codebase:
| Code | Location | Meaning |
|---|---|---|
| `[MNER-E-INFRA-001]` | `dashboard.py:101` | Required infra (Redis/TimescaleDB) missing on start |
| `MNER PONS-E-COST-803` | PonsExecutionCost | Cost computation failure |
| `MNER PONS-E-COST-804` | PonsExecutionCost | Cost computation failure variant |
| `MNER COUNCIL-E-SPR-701` | SpreadEngine | Invalid quote (bid ≤ 0 or ask < bid) → ATR fallback |
| `MNER COUNCIL-E-SPR-702` | SpreadEngine | Missing column → ATR fallback |
| `MNER COUNCIL-E-SPR-703` | SpreadEngine | General spread evaluate() error |
| `MNER COUNCIL-E-SPR-704` | SpreadEngine | Unexpected runtime exception |
| `MNER ALLOC-E-SIZE-902` | AllocationGland | Zero stop distance |
| `MNER ALLOC-E-SIZE-903` | AllocationGland | Risk cap breach — qty clamped |
| `MNER ALLOC-E-SIZE-904` | AllocationGland | Allocator runtime exception |

**The neural log div is named `mnerLog` in the HTML** — the intent is that MNER events surface there. However, **all MNER codes go to `print()` (server stdout), not through the SSE event bus**. The `mnerLog` div only shows SSE events (`pulse`, `engine`, `furnace`, `error`, `system`).

This means: if AllocationGland trips `ALLOC-E-SIZE-902`, it appears in the server terminal, not in the dashboard log. The dashboard neural log shows the outcome (approved/rejected in the pulse event) but not the MNER diagnostic code that explains why. The structured error system and the live log are decoupled.
