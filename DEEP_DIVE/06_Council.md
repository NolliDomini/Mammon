# Deep Dive: Council — Environment Intelligence Authority

## 1. Purpose & Role
Council is the **environmental sensor**. It runs every pulse (SEED, ACTION, MINT) to maintain continuous situational awareness. It produces a single `confidence` score (0–1) that represents how favorable the current market environment is for trading, and writes a `regime_id` that can override indicator weights dynamically.

---

## 2. Inputs & Outputs

**Input:** `frame.market.ohlcv` — trailing OHLCV context (50 bars)

**Writes to `frame.environment`:**
| Field | Source |
|---|---|
| `confidence` | Weighted blend of 5 indicators |
| `atr` | Latest ATR value |
| `atr_avg` | 50-bar ATR average |
| `adx` | Latest ADX value |
| `volume_score` | Relative volume score |
| `bid_ask_bps` | Spread in basis points |
| `spread_score` | Normalized spread score |
| `spread_regime` | `TIGHT / NORMAL / WIDE / STRESSED` |

**Writes to `frame.risk`:**
| Field | Source |
|---|---|
| `regime_id` | 16-char D_A_V_T string |

---

## 3. Confidence Formula

```
confidence = (atr_score × w_atr) + (adx_score × w_adx) + (vol_score × w_vol)
           + (vwap_score × w_vwap) + (spread_score × w_spread)
           ÷ sum(weights)
```

**Default weights:**
| Indicator | Weight | Dominance |
|---|---|---|
| ADX (trend strength) | 0.60 | **Primary driver** |
| Volume ratio | 0.30 | Secondary |
| Spread score | 0.15 | Friction penalty |
| ATR ratio | 0.06 | Minor |
| VWAP distance | 0.04 | Minor |

Note: weights sum to 1.15, then normalized — ADX alone can account for ~52% of final score.

---

## 4. Indicator Scoring

| Indicator | Computation | Score range |
|---|---|---|
| **ATR** | `clip(atr/atr_avg - 0.5, 0, 1)` — expansion above average | 0–1 |
| **ADX** | `clip(adx/50, 0, 1)` — raw trend strength | 0–1 |
| **Volume** | `clip((vol/avg_vol)/2, 0, 1)` — relative volume | 0–1 |
| **VWAP** | `clip(0.5 + pct_dist_from_vwap, 0, 1)` — price vs VWAP | 0–1 |
| **Spread** | `1 - clip(spread_bps/(atr_bps × scalar), 0, 1)` — tighter = higher | 0–1 |

All computed via Numba JIT kernels (`calculate_atr_njit`, `calculate_adx_njit`, `calculate_vwap_njit`).

---

## 5. Regime ID — `D_A_V_T`

16-char string encoding 4 binned dimensions:
- `D` — VWAP distance (bins: -0.05, 0, 0.05)
- `A` — ATR ratio (bins: 0.1, 0.3, 0.6)
- `V` — Volume ratio (bins: 0.2, 0.4, 0.7)
- `T` — Trend/ADX (bins: 0.25, 0.5, 0.75)

Each dimension → integer 0–3. Example: `D2_A1_V3_T2`

Used to look up `regime_weight_table` in hormonal vault — matching regime overrides the default indicator weights. Prefix matching supported (e.g. `D2_A1` matches any V/T).

---

## 6. SpreadEngine (Piece 55)

Runs **first** in the Council cycle (before ATR/ADX/Vol/VWAP) to populate `frame.environment.spread_*` before the confidence blend.

Priority path:
1. Live quote: reads `bid`/`ask` columns from `frame.market.ohlcv`
2. ATR fallback: if bid/ask missing or invalid → `spread_bps = atr_bps × spread_atr_ratio`
3. Error guard: sets `spread_score = 0.0` on unexpected failure

Regime thresholds (from Gold `frame.standards`):
- TIGHT ≤ 5 bps / NORMAL ≤ 15 bps / WIDE ≤ 50 bps / STRESSED > 50 bps

Spread runs on SEED and ACTION only — skipped at MINT.

---

## 7. Dependencies

| Dependency | Direction | Purpose |
|---|---|---|
| `BrainFrame` | read/write | Source data + environment slot writes |
| `Hippocampus.Archivist.librarian` | outbound | Reads `hormonal_vault` for regime weight table |
| Numba JIT kernels | internal | ATR, ADX, VWAP computation |
| `SpreadEngine` | internal | Bid/ask friction scoring |

---

## 8. Failure Modes

- **Calculation failure**: falls back to neutral scores (all 0.5), logs error code `SOUL-E-P30-213` — cycle continues
- **Insufficient history** (`< 2 rows`): returns 0.5, sets status `INSUFFICIENT_HISTORY`
- **Spread missing bid/ask**: ATR fallback applied, logs `COUNCIL-E-SPR-702`
- **Spread invalid quote**: ATR fallback applied, logs `COUNCIL-E-SPR-701`
- **Spread runtime error**: `spread_score = 0.0` (penalizes confidence), logs `COUNCIL-E-SPR-704`

---

## 9. Non-Obvious Behavior

- **Spread runs before other indicators** — it writes `frame.environment.atr` dependency... except it reads `frame.environment.atr` which hasn't been computed yet at that point. SpreadEngine's ATR fallback reads `frame.environment.atr` which is the *previous pulse's* ATR value.
- **Regime weight override can exceed 1.0 unnormalized** — the spread weight is 0.15 on top of the 1.0 base, so raw weights sum to 1.15. Division normalizes this, but a regime override that sets all weights high could artificially concentrate confidence.
- **`frame.risk.regime_id` is written by Council** — not Left Hemisphere. The regime that drives walk engine seeding originates here.
- **`calculate_cortex_cache()`** is a bulk DuckDB precalc method — it appears to be a maintenance/batch tool, not called in the live pulse path.

---

## 10. Open Questions / Risks

- **SpreadEngine ATR dependency order**: spread runs first, but needs ATR — uses stale previous-pulse ATR. Fine at steady state, wrong on first pulse.
- **ADX dominates at 52%+**: if ADX fires high on a choppy bar, Council will approve despite poor volume/spread conditions.
- **Regime override prefix matching is ordered by dict iteration** — Python dicts are insertion-ordered but the vault JSON load order may not be predictable if multiple prefixes could match.
- **Minimum history for ATR requires 50 bars** (`atr_avg_window=50`) — early in a session or after restart, ATR score returns 0.0, dragging confidence down even in healthy markets.

---

## 11. Deep Investigation Findings

### Finding 1: SpreadEngine ATR Circular Dependency

SpreadEngine runs **before** ATR is computed in the Council cycle. Its ATR fallback path reads:
```python
spread_bps = frame.environment.atr * spread_atr_ratio
```

`frame.environment.atr` is written by Council's own ATR kernel — which hasn't run yet at the moment SpreadEngine needs it. SpreadEngine reads the **previous pulse's** `atr` value stored on the frame (structure/environment slots are preserved across `reset_pulse()`).

At steady state this is benign — ATR changes slowly. On the **first pulse** after startup, `frame.environment.atr = 0.0` (BrainFrame default), so SpreadEngine's ATR fallback produces `spread_bps = 0.0` and `spread_score = 1.0` (maximum) regardless of actual market conditions. The first pulse's confidence is overstated.

---

### Finding 2: Council Writes `frame.risk.regime_id` — TurtleWalk Overwrites It

Council writes `frame.risk.regime_id` from its D_A_V_T computation. `QuantizedGeometricWalk.build_seed()` runs next in the Soul sequence and writes its own `regime_id` to the same field with different bin thresholds. TurtleWalk's value is always the final one on `frame.risk.regime_id`.

The practical impact is that Council's `regime_weight_table` lookup (which uses Council's binning) and TurtleWalk's Walk Silo discharge (which keys on `frame.risk.regime_id` — TurtleWalk's binning) may reference different regime strings for the same market state. See `07_Left_Hemisphere.md` Section 11 for the full overwrite sequence.

---

### Finding 3: Production Lobes Use `Librarian` Test Shim

Council instantiates `Librarian()` (the SQLite test shim) directly for its DB writes, not `MultiTransportLibrarian`. This means Council's `callosum_mint`, `cortex_precalc`, and related writes go to a per-instance SQLite connection, not the shared DuckDB analytical store. The same pattern applies to TurtleMonte, Callosum, and Gatekeeper. The `09_Hippocampus.md` documents this at the infrastructure level — the consequence for each lobe is that its analytical writes land in a test SQLite file rather than the production DuckDB schema.
