# Deep Dive: Right Hemisphere — The Structure Painter

## 1. Purpose & Role
Right Hemisphere is the **breakout detector**. It reads the current OHLCV context from `BrainFrame.market`, computes Donchian-style rolling high/low levels, and writes a binary `tier1_signal` to `BrainFrame.structure`. That signal is the master gate for all downstream processing in Soul.

---

## 2. Inputs & Outputs

**Input:** `frame.market.ohlcv` — the trailing context DataFrame (up to 50 bars from Thalamus)

**Output (writes to `frame.structure`):**
| Field | Value |
|---|---|
| `price` | Latest close |
| `active_hi` | Max high over last `active_gear` bars |
| `active_lo` | Min low over last `active_gear` bars |
| `gear` | The gear used for this pulse |
| `tier1_signal` | `1` if `close > prev_active_hi`, else `0` |

Returns `(df, strikes_list)` — strikes are metadata dicts logged when signal fires.

---

## 3. The Signal Logic

```
prev_active_hi = max(highs[-(gear+1):-1])   # prior window high (excludes current bar)
tier1_signal   = 1 if current_close > prev_active_hi else 0
```

**It's a Donchian breakout**: close must exceed the highest high of the *previous* `gear`-bar window. The current bar is excluded from the reference high to prevent self-confirmation.

---

## 4. Gear Resolution

`active_gear` is resolved in priority order:
1. `self.config["active_gear"]` — set directly on instance
2. `frame.standards["active_gear"]` — from Gold vault params
3. Falls back to `0` → safe reset, `tier1_signal = 0`

Current live default: **gear = 3** (scalp_v1_20260419 profile).

---

## 5. Failure / Safe Reset

Any of these triggers `tier1_signal = 0` and zeroes structure:
- `active_gear <= 0`
- Empty or non-DataFrame OHLCV
- Missing `high`/`low`/`close` columns
- Non-numeric OHLCV values
- `len(df) < active_gear` (insufficient history — price is still written)

Fail-safe is a hard invariant: no downstream lobe should ever see a stale or partial structure.

---

## 6. Unimplemented Tiers

| Module | Tier | Status |
|---|---|---|
| `MomentumEngine` | Tier 2 — MACD Reversals | Stub only |
| `VelocityEngine` | Tier 3 — Bollinger Speed | Stub only |
| `LevelsEngine` | Tier 4 — Pivot Scanner | Stub only |

**Only Tier 1 (SnappingTurtle) is live.** The system runs on Donchian breakout alone.

---

## 7. Dependencies

| Dependency | Direction | Purpose |
|---|---|---|
| `BrainFrame` | read/write | Reads `market.ohlcv`, writes `structure.*` |
| Gold vault `active_gear` | config | Gear size — hot-reloadable |

No external I/O, no persistence, no broker calls.

---

## 8. Critical Function

`SnappingTurtle.on_data_received()` — the entire module. ~50 lines. Numpy vectorized, no loops.

---

## 9. Non-Obvious Behavior

- **`prev_active_hi` excludes the current bar** — the breakout reference is the *prior* window's high, not the rolling max including today. A bar cannot break out against itself.
- **Insufficient history still sets `frame.structure.price`** — so downstream lobes always have a valid price even when the signal is suppressed.
- **`tier1_signal` persists across `reset_pulse()`** — `reset_pulse` does not clear `frame.structure`. If Right Hemisphere isn't called (e.g., lobe error), the previous pulse's signal remains live. This is a latent risk.

---

## 10. Open Questions / Risks

- **Tiers 2–4 are stubs** — the system is operating on a single signal type with no confirmation from momentum or velocity.
- **`tier1_signal` not cleared by `reset_pulse()`** — a lobe crash on Right Hemisphere could leave a stale `tier1_signal = 1` from the prior pulse, causing Soul to run the full execution path on bad data.
- **Gear = 3 at current profile** — very short lookback for a breakout signal; susceptible to noise on low-volume bars.
