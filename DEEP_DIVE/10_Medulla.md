# Deep Dive: Medulla — Policy & Ledger Authority

## 1. Purpose & Role
Medulla owns **money accounting and trade policy**. It contains three distinct systems: Gatekeeper (already covered in `08_Corpus_Gatekeeper.md`), TreasuryGland (the ledger), and AllocationGland (position sizing). Brain Stem calls all three.

---

## 2. TreasuryGland — The Ledger

### Schema (SQLite via Librarian)

| Table | Purpose |
|---|---|
| `money_orders` | Full intent lifecycle: ARMED → FILLED / CANCELED / REJECTED / TIMEOUT |
| `money_fills` | One row per fill — qty, adjusted price, slippage, fee |
| `money_positions` | Running position per (symbol, mode): qty, avg_price, unrealized/realized PnL |
| `money_pnl_snapshots` | Point-in-time PnL snapshot after every transition |
| `money_audit` | Full JSON audit log of every event |

**Primary key on `money_orders`**: `intent_id` — format: `{symbol}:{epoch_ms}:{uuid[:8]}`

**Mode isolation**: every query filters on `mode` — DRY_RUN, PAPER, LIVE, BACKTEST never mix.

### Intent Lifecycle
```
record_intent()    → ARMED         (called at ACTION)
cancel_intent()    → CANCELED      (MINT: mean-dev or stale-price kill)
reject_intent()    → REJECTED      (MINT: adapter failure, invalid payload)
timeout_intent()   → TIMEOUT       (timing inhibit path)
fire_intent()      → FILLED        (MINT: successful execution)
partial_fill_intent() → PARTIAL_FILLED
```

Every transition calls `_audit()` (JSON blob to `money_audit`) and `_snapshot_pnl()`.

### Fill Price Calculation
```
slip_bps = base_slippage_bps + (vol_mult × (sigma/price_ref × 10000))
adjusted_price = raw_price × (1 + slip_frac)   # BUY: price goes up
slippage_cost  = |adjusted - raw| × qty
fee            = notional × (fee_bps / 10000)
```
Both slippage and fee default to 0.0 unless configured — in DRY_RUN, fills record at exact price.

### Position Accounting
- **BUY**: weighted average cost basis (`(old_qty × old_avg + new_qty × new_price) / total_qty`)
- **SELL**: realizes PnL = `(fill_price - avg_price) × qty`; position qty decrements
- Unrealized PnL recalculated at each fill using fill price as proxy for market price

### Key Queries Used by Brain Stem
- `get_open_positions_count()` → used for `max_open_positions` guardrail
- `get_realized_pnl_for_day()` → used for `max_daily_realized_loss` circuit breaker
- `reconcile_paper_with_broker()` → PAPER mode drift detection

---

## 3. AllocationGland — Position Sizing

**Not wired into Soul's live cycle** in the current orchestrator code — `score_tier` → `gatekeeper.decide()` runs, but `AllocationGland.allocate()` is not called. Brain Stem uses `frame.command.sizing_mult` (set flat by Gatekeeper) as its qty. AllocationGland exists as a more sophisticated sizer but appears to be dormant.

### Formula (when used)
```
raw_conviction       = clamp(z_distance / max_z, 0, 1)
cost_penalty         = total_cost_bps / cost_penalty_divisor
adjusted_conviction  = raw_conviction × (1 - clamp(cost_penalty, 0, max_cost_penalty))

stop_distance = price - valuation.lower_band
raw_qty       = (equity × risk_per_trade_pct × adjusted_conviction) / stop_distance

qty = min(raw_qty, max_notional/price, max_qty)
qty = 0 if qty < min_qty
```

Writes to: `frame.command.qty`, `frame.command.notional`, `frame.command.size_reason`, `frame.command.risk_used`, `frame.command.cost_adjusted_conviction`

---

## 4. Orders Module

Two thin wrappers over Alpaca `client.submit_order()`:
- `buy(client, symbol, qty)` → market order, GTC
- `sell(client, symbol, qty)` → market order, GTC
- Returns `None` on failure (logged, not raised)
- `calculate_position_size()` is a simple `equity × risk_pct / stop_distance` helper — not used in the live path (Brain Stem uses Gatekeeper's `sizing_mult` directly)

---

## 5. Dependencies

| Dependency | Direction | Purpose |
|---|---|---|
| `Hippocampus.Archivist.Librarian` | outbound | All reads/writes (SQLite via test Librarian, not MultiTransport) |
| `BrainFrame` | inbound | AllocationGland reads `valuation`, `execution`, `structure`, `standards` |
| `alpaca.trading.TradingClient` | outbound (Orders) | Physical order submission |

---

## 6. Failure Modes

- **Invalid intent payload** (`record_intent`): warns and returns silently — intent not recorded
- **Invalid fill payload** (`fire_intent`): calls `reject_intent()` and returns — no crash
- **AllocationGland error**: fail-closed — sets `qty=0`, `ready_to_fire=False`, `approved=0`
- **Orders `buy()`/`sell()` failure**: returns `None`, Brain Stem then records `REJECT_ADAPTER_FAILURE`

---

## 7. Non-Obvious Behavior

- **TreasuryGland uses `Librarian()` (SQLite shim)**, not `MultiTransportLibrarian` — all money state is in a SQLite file, not DuckDB. The `money_orders` table described in the TimescaleDB migration path (via Librarian.write transport="timescale") is a *different* table in TimescaleDB — both exist in parallel for different purposes.
- **`_transition_intent` is idempotent**: the `WHERE status != 'FILLED'` guard prevents a FILLED order from being overwritten — once filled, the record is immutable.
- **Slippage and fee default to 0.0 in DRY_RUN** unless `slippage_bps` and `fee_bps` are set in config. Backtest performance will look better than live if these aren't configured.
- **AllocationGland dormancy**: `frame.valuation.z_distance` and `frame.valuation.lower_band` are written by Brain Stem's valuation gate — but AllocationGland isn't called in the Soul cycle, meaning the sophisticated conviction-based sizing is unused. Gatekeeper's flat `sizing_mult` drives Brain Stem instead.
- **PnL snapshots accumulate unbounded** — `money_pnl_snapshots` gets a new row after every fill transition. No pruning.

---

## 8. Open Questions / Risks

- **AllocationGland is dead code in the live path** — the sophisticated cost-adjusted sizing is implemented but not wired into Soul. Brain Stem fires based on Gatekeeper's flat `sizing_mult`.
- **`gatekeeper_sizing_mult = 0.01`** is the live sizing parameter (from `hormonal_vault.json`). Every approved trade fires at exactly 0.01 units regardless of equity, conviction, or volatility. For BTC at $65,000 this is a $650 notional. Not risk-pct based — flat fractional unit.
- **SQLite concurrency**: TreasuryGland uses a per-instance SQLite connection. If Brain Stem and any other lobe instantiate TreasuryGland separately, they get separate connections with no coordination.
- **Unrealized PnL uses fill price as market proxy** — `_apply_fill_to_position` sets `market_price = fill_price`. Unrealized PnL goes stale immediately after a fill and is never updated until the next fill.
- **No SELL intent tracking**: Brain Stem calls `_fire_physical("SELL")` directly without going through `record_intent()` first — sell exits are not pre-recorded as ARMED intents, only as fills.
