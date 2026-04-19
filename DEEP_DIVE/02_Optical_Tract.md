# Deep Dive: Optical Tract — The Pulse Broadcast Bus

## 1. Purpose & Role
Optical Tract is the **nervous system relay** — a synchronous pub/sub fan-out that delivers pulse DataFrames from any publisher (primarily Thalamus) to all registered subscriber lobes. It does not transform, filter, or route — it broadcasts everything to everyone, in registration order.

---

## 2. Inputs & Outputs

**Input to `spray(df)`:**
- Any `pd.DataFrame` — typically a pulse-wrapped context frame from Thalamus
- Expected to have `pulse_type` and `symbol` columns (used for telemetry/audit only — not enforced)

**Output of `spray()`:**
- Returns a structured `Dict` summary: delivered count, failed count, per-subscriber latency, errors
- Side effect: calls `on_data_received(df)` on every registered subscriber

---

## 3. Key Data Structures

| Name | Type | Purpose |
|---|---|---|
| `subscribers` | `List[Any]` | Ordered list of subscriber instances |
| `subscriber_names` | `List[str]` | Fixed-size (20) name array, indexed parallel to subscribers |
| `delivery_stats` | `np.ndarray[float64]` | Per-subscriber delivery time in ms (reset each spray) |
| `last_delivery` | `dict` | Full telemetry snapshot of most recent spray call |

---

## 4. Control Flow

```
spray(df)
  → guard: return "skipped" if df is None or empty
  → extract pulse_type, symbol from df tail
  → for each subscriber (in order):
      → sub.on_data_received(df)
      → on exception: log error, write to broadcast_audit via Librarian (best-effort)
      → record per-subscriber latency
  → return summary dict
```

Fan-out is **not short-circuited** — a failing subscriber does not stop delivery to subsequent subscribers.

---

## 5. Dependencies

| Dependency | Direction | Purpose |
|---|---|---|
| `Hippocampus.Archivist.librarian` | outbound | Writes delivery errors to `broadcast_audit` table (TimescaleDB transport) |
| Any lobe with `on_data_received(df)` | outbound | The subscriber contract |

The `librarian` write on error is wrapped in a bare `except: pass` — audit failure is silent.

---

## 6. State & Persistence

- **In-memory only**: subscriber list, names, last_delivery stats
- **Audit persistence**: failed deliveries are written to `broadcast_audit` (timestamp, symbol, pulse_type, target_lobe, error_msg) via Librarian/TimescaleDB — best-effort, not guaranteed

---

## 7. Concurrency Model

Fully **synchronous**. `spray()` blocks until all subscribers have been called. There is a 50ms soft budget tracked in telemetry but **not enforced** — a slow subscriber will delay all subsequent subscribers and the caller. No timeout, no async, no thread pool.

---

## 8. Configuration

| Param | Default | Effect |
|---|---|---|
| `MAX_SUBSCRIBERS` | `20` | Hard cap on named subscriber slots (list itself is uncapped) |
| `delivery_budget_ms` | `50.0` | Soft budget — telemetry only, not enforced |

---

## 9. Failure Modes

- **Subscriber exception**: caught, logged to `last_delivery["errors"]`, written to audit DB, fan-out continues
- **Audit write failure**: silently swallowed — no indication a delivery error was lost
- **Subscriber name overflow**: if more than 20 subscribers register, names beyond index 19 are not stored (list still grows, names array does not)
- **Empty payload**: `spray()` returns immediately with `status: "skipped"` — no subscribers called

---

## 10. Critical Functions

| Function | Why it matters |
|---|---|
| `spray(df)` | The entire runtime — this is the only thing that matters at runtime |
| `subscribe(lobe, name)` | Wires a lobe into the broadcast; duplicate-guards by identity |
| `LegacyTwoArgSubscriberAdapter` | Bridges old `on_data_received(pulse_type, data)` signatures to the modern single-arg contract |

---

## 11. Non-Obvious Behavior

- **No payload mutation guarantee enforcement**: the README states "no silent mutation of input dataframe" as an invariant, but this is on-trust — nothing in the code prevents a subscriber from modifying the DataFrame in place, which would corrupt delivery to all subsequent subscribers.
- **`librarian` is imported as a singleton instance** (`from ... import librarian`), not a class — it's a module-level shared object.
- **`delivery_stats` resets every spray call** (`fill(0.0)`) — only the most recent spray is visible in telemetry.
- **Legacy adapter is explicit**: the system no longer auto-detects 2-arg signatures at runtime. Old subscribers must be wrapped manually with `LegacyTwoArgSubscriberAdapter`.

---

## 12. Open Questions / Risks

- **No async/queue**: a single slow subscriber (e.g., a lobe doing heavy compute in `on_data_received`) will delay every pulse delivery system-wide.
- **DataFrame mutation risk**: if any subscriber mutates the shared df, downstream subscribers see corrupted data silently.
- **Audit reliability**: error audit writes are best-effort with silent failure — in a high-error scenario, the audit trail may be incomplete.
- **Subscriber cap asymmetry**: `MAX_SUBSCRIBERS=20` only caps the name array, not the list — telemetry silently drops names for subscriber 21+.
