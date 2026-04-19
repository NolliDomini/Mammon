# Deep Dive: Pineal — Circadian Memory Custodian

## 1. Purpose & Role
Pineal is the **memory janitor**. It runs every MINT pulse to purge stale rows from all SQLite vaults, enforcing time-based retention windows so DBs don't grow unbounded. It also owns the post-Fornix staging lifecycle — deciding whether accumulated history_synapse tickets are archived or preserved.

Named after the pineal gland, which regulates circadian rhythm and biological housekeeping.

---

## 2. When Does It Run?

- `secrete_melatonin()` — called every MINT by Soul Orchestrator (live loop)
- `finalize_fornix_staging()` — called by Fornix after DiamondGland completes (batch path)

---

## 3. Inputs & Outputs

**Input:**
- Four SQLite vaults: `memory_db`, `synapse_db`, `optimizer_db`, `control_db`
- `diamond_consumed` flag from DiamondGland return value (Fornix path)

**Output:**
- Rows deleted from SQLite tables beyond retention window
- `history_synapse` table wiped (only if Diamond consumed staging)
- No vault writes — purely destructive/archival

---

## 4. Retention Map

| Table | DB | Retention |
|---|---|---|
| `turtle_monte_mint` | memory_db | 1 hour |
| `council_mint` | memory_db | 6 hours |
| `synapse_mint` | synapse_db | 2,160 hours (90 days) |
| `optimizer_runs` | optimizer_db | configurable |
| `control_*` | control_db | configurable |

The 90-day synapse window is the training horizon for DiamondGland and SynapseRefinery — Pineal's purge schedule directly sets how much history those systems can see.

---

## 5. Control Flow

```
secrete_melatonin()                        # every MINT
  → now = current UTC time
  → DELETE FROM turtle_monte_mint WHERE ts < now - 1h
  → DELETE FROM council_mint WHERE ts < now - 6h
  → DELETE FROM synapse_mint WHERE ts < now - 2160h
  → (optimizer/control purges if configured)

finalize_fornix_staging(diamond_consumed)  # Fornix post-replay
  → if diamond_consumed:
      → archive history_synapse → permanent synapse_mint
      → DELETE FROM history_synapse
  → else:
      → preserve history_synapse (Diamond gets another chance next run)
```

---

## 6. The Staging Wipe Decision

Pineal is the **sole authority** on whether Fornix staging is cleared. The logic:

- Diamond consumed → safe to wipe; tickets are promoted to permanent synapse history
- Diamond failed / insufficient data → preserve staging; next Fornix run appends to it

This prevents data loss when Diamond fails to reach 50-ticket threshold for a small symbol set.

---

## 7. Dependencies

| Dependency | Direction | Purpose |
|---|---|---|
| `memory_db` (SQLite) | write | Purge turtle/council mint rows |
| `synapse_db` (SQLite) | write | Purge old synapse tickets; archive staging |
| `optimizer_db` (SQLite) | write | Purge optimizer run history |
| `control_db` (SQLite) | write | Purge control table rows |
| `DiamondGland` return value | inbound | Gate on staging wipe |

---

## 8. Non-Obvious Behavior

- **Purge runs on every MINT in the live loop.** For a 5m pulse system this is ~288 purge cycles/day — each is a DELETE WHERE ts < cutoff. At scale (millions of rows) this can become a latency contributor.
- **`turtle_monte_mint` 1-hour window is very tight.** Walk data from Left Hemisphere is only retained for the last ~12 MINT cycles. If something consumes walk history more than 1 hour later, it gets nothing.
- **Staging wipe is all-or-nothing.** There's no partial archive — if Diamond consumed, all of `history_synapse` is wiped regardless of how many symbols contributed.
- **No confirmation that archive succeeded before wipe.** If the INSERT into permanent `synapse_mint` fails mid-way, the subsequent DELETE still runs — silent data loss risk.
- **Pineal has no awareness of TimescaleDB.** Purges only touch SQLite. The TimescaleDB audit ledger (TreasuryGland) manages its own retention independently.

---

## 9. Open Questions / Risks

- **Archive-then-wipe race.** If `finalize_fornix_staging()` is called while `secrete_melatonin()` is mid-purge on `synapse_db`, both hold SQLite write locks — potential contention or deadlock on high-activity runs.
- **90-day window is a magic number.** It's not derived from any regime analysis — it's a hard-coded constant. If market regimes shift faster, 90 days of stale signal degrades DiamondGland quality.
- **No metrics on what was purged.** Pineal deletes silently. There's no log of row counts removed, making it impossible to detect runaway growth or accidental over-purge.
