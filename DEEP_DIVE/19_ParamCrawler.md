# Deep Dive: ParamCrawler — Dual-Mode Genetic Engine

## 1. Purpose & Role
ParamCrawler is a **live-pulse genetic engine** running two concurrent modes every MINT:

- **MINE mode** — replays historical param sets against recent synapse tickets, scores them, and installs the top performers into Silver (feeding Pituitary's GP training set)
- **PROMOTE mode** — soak-tests a Titanium challenger over a configurable window and promotes it to Gold if it outperforms the incumbent

It is the bridge between the batch optimizer (Hospital) and the live hormone hierarchy — the mechanism by which historically-validated param sets re-enter the vault without requiring a full Fornix run.

---

## 2. When Does It Run?

Called on every **MINT pulse** by Soul Orchestrator (`crawl(pulse_type, frame)`). SEED and ACTION pulses are immediately ignored.

MINE mode has its own cadence gate — it fires only once per `crawler_mine_interval × 300` seconds (default: 12 intervals × 300s = every 3,600 seconds / ~60 minutes live).

---

## 3. MINE Mode Flow

```
_run_mine_mode(vault, frame)
  → cadence check: skip if < interval since last mine
  → SynapseRefinery.harvest_training_data(hours=lookback)    # synapse tickets
  → librarian.get_param_history(limit=50)                    # last 50 historical params
  → for each historical param set:
      → _replay_params(params, tickets)
          → _re_synthesize_tier_score(params, tickets)
              → scores = monte * callosum_w_monte + tier1_signal * callosum_w_right
          → fitness = mean(scores × (1 + tanh(realized_pnl)))
  → sort by fitness descending → top N
  → librarian.record_silver_candidate() for each winner
```

**Key formula — replay kernel:**
```
tier_score_i = (monte_score_i × callosum_w_monte) + (tier1_signal_i × callosum_w_right)
fitness      = mean(tier_score × (1 + tanh(realized_pnl)))
```

If `realized_pnl` is absent from tickets, it defaults to `ones` — the fitness reduces to mean re-synthesized tier score alone.

---

## 4. PROMOTE Mode Flow

```
_run_promote_mode(vault, frame)
  → if no titanium or soak_active=False: return
  → append frame.risk.monte_score to titanium.soak_scores
  → if len(soak_scores) < soak_window: persist and return (still soaking)
  → avg_titanium_fitness = mean(soak_scores)
  → if avg_titanium_fitness > gold_fitness + promotion_delta:
      → librarian.install_gold_params(titanium.params, fitness, ...)
      → vault["titanium"] = None  (clear soak)
  → else:
      → vault["titanium"] = None  (discard)
```

Default soak_window: 12 MINT pulses (~60 minutes of market time at 5m bars).
Default promotion_delta: 0.05 — Titanium must beat Gold by at least 5 percentage points.

---

## 5. Cadence Summary

| Mode | Trigger | Default Frequency |
|---|---|---|
| MINE | MINT + cadence gate | ~every 60 min |
| PROMOTE | MINT + soak_active flag | Every MINT while soaking |

Both `crawler_mine_interval`, `crawler_lookback_hours`, `crawler_silver_top_n`, `soak_window`, and `promotion_delta` are **pulled from Gold params** at runtime — they are evolvable by the optimizer.

---

## 6. Dependencies

| Dependency | Direction | Purpose |
|---|---|---|
| `SynapseRefinery` | outbound | Harvests recent synapse tickets for replay |
| `MultiTransportLibrarian` | outbound | Vault read/write, param history, Silver write |
| `BrainFrame.risk.monte_score` | inbound | Live soak score signal |
| `vault["titanium"]` | read/write | Soak candidate state |
| `vault["gold"]["params"]` | read | Cadence/threshold config + incumbent fitness |

---

## 7. Non-Obvious Behavior

- **MINE cadence is wall-clock, not MINT-count.** `last_mine_ts` is initialized to 0 — MINE fires on the very first MINT after startup, regardless of interval. The second fire waits the full interval from that first run.
- **Promotion uses `frame.risk.monte_score` as the soak signal**, not Titanium's own predicted fitness. The soak measures how the *current market regime* is scoring, not how Titanium's params perform against it. If the market is trending poorly, Titanium soaks get unfairly penalized regardless of params.
- **Titanium params are never re-evaluated during soak.** The soak accumulates live monte_scores passively — there is no active simulation of Titanium against those bars. It's a passive ambient signal, not a forward test.
- **MINE re-synthesizes tier_score using candidate weights, not Gold weights.** This is correct by design — it's asking "if we had used this candidate's Callosum blend, what would the score have been?" But it only re-blends `callosum_w_monte` and `callosum_w_right` — the other 21 parameters are not replayed (Brain Stem, Gatekeeper, Council weights are ignored).
- **`realized_pnl` is almost never present.** The SynapseRefinery schema doesn't write `realized_pnl` to synapse tickets — the fitness kernel almost always runs in the `ones` fallback, making it equivalent to mean re-synthesized tier score. The P&L grounding is aspirational, not live.
- **Promotion fallback writes Gold directly to vault dict.** If `librarian.install_gold_params()` fails, the fallback vault write skips param DB logging entirely — that Gold coronation has no audit trail.

---

## 8. Open Questions / Risks

- **Silver contamination.** MINE runs every ~60 minutes, potentially re-populating Silver with the same top-50 historical param sets repeatedly. If market conditions haven't changed, Silver accumulates duplicates, and Pituitary GP trains on a redundant dataset.
- **Soak signal is the wrong proxy.** Using `monte_score` from the live pulse to evaluate Titanium measures market difficulty, not Titanium's fitness. A simpler and more direct evaluation would be to replay Titanium's params against the last N synapse tickets — the same method MINE uses.
- **Gold params control crawler behavior.** Since `crawler_mine_interval`, `soak_window`, and `promotion_delta` are read from Gold params, a bad GP mutation that changes these values can disable or over-trigger the crawler — a feedback loop where a poor Gold can cripple its own replacement mechanism.
