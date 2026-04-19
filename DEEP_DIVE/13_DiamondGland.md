# Deep Dive: DiamondGland — Bayesian Safety Rail Governor

## 1. Purpose & Role
DiamondGland is the **slow-brain Bayesian search engine**. It runs after Fornix completes a historical replay, analyzes the accumulated synapse tickets, and derives mathematically-grounded **safety rails** — per-parameter min/max bounds that constrain all future GP mutations in Pituitary.

It answers: *"Given what actually happened historically, what parameter ranges are associated with high fitness?"*

---

## 2. When Does It Run?

Called by Fornix at the end of a replay run (`_run_diamond()`), if `history_synapse` has ≥ 50 tickets. Also called by `MetabolismDaemon` as a standalone batch process.

**Not in the live pulse loop.** Output (safety rails in vault) is consumed by Pituitary GP mutation on the next live cycle.

---

## 3. Inputs & Outputs

**Input:**
- `SynapseRefinery.harvest_training_data(hours=24)` — pulls recent synapse tickets and computes `realized_fitness`
- `Hospital/Optimizer_loop/bounds.py` — `MINS`, `MAXS`, `normalize_weights`

**Output:**
- `vault["diamond_rails"]["bounds"]` — per-param `{min, max}` dict written to `hormonal_vault.json`
- `DiamondScribe` silo — training matrix dumped for reproducibility

---

## 4. Control Flow

```
DiamondGland.perform_deep_search()
  → SynapseRefinery.harvest_training_data(hours=24)
      → pulls synapse tickets, computes realized_fitness
  → guard: < 50 rows → abort
  → DiamondScribe.dump(data)           # write to private silo
  → load training matrix from silo
  → extract X (23-D param vectors), y (realized_fitness)
  → fit Matern(ν=1.5) GP on X, y      (n_restarts=5)
  → sample 5,000 random candidates within MINS/MAXS
  → normalize weight groups on each
  → GP.predict(X_test) → y_mean
  → safe_island = X_test[y_mean > 0.75]
      → fallback: top 10th percentile if no island found
  → rails[param] = {min: min(safe_island[:,i]), max: max(safe_island[:,i])}
  → _update_vault(rails)               # write to hormonal_vault.json
```

---

## 5. The Safety Rail Concept

The rails are not hard performance thresholds — they are **observed parameter ranges** within the predicted high-fitness region of the GP surface.

```
safe_island = candidates where GP predicts fitness > 0.75
rails[param].min = lowest value of that param seen in safe_island
rails[param].max = highest value seen in safe_island
```

These become the clamping bounds applied in `Pituitary._run_gp_mutation()` step 7 — any GP-derived candidate is clipped to stay within rails before coronation.

---

## 6. Dependencies

| Dependency | Direction | Purpose |
|---|---|---|
| `SynapseRefinery` | outbound | Harvests + computes realized_fitness from synapse history |
| `DiamondScribe` | outbound | Writes training matrix to private silo DB |
| `hormonal_vault.json` | read/write | Target for rail updates |
| `Hospital.bounds` MINS/MAXS | inbound | Absolute parameter bounds for candidate sampling |
| `sklearn.GaussianProcessRegressor` | internal | Matern GP fit |

---

## 7. Realized Fitness — The Key Input

DiamondGland's quality depends entirely on what `SynapseRefinery.harvest_training_data()` returns as `realized_fitness`. Unlike Hospital's predicted scores, this should be grounded in actual historical signal quality. The refinery's computation of this field is the critical dependency to understand.

---

## 8. Non-Obvious Behavior

- **5,000 candidates, not the same 500 as Pituitary GP.** Diamond uses a larger test set for rail extraction — it's searching for the *boundaries* of a high-fitness region, not the single peak.
- **Rails are ranges, not targets.** A wide rail on a parameter means Diamond found high-fitness candidates across a broad range — low confidence. A narrow rail means the fitness surface is sensitive to that parameter.
- **Fallback to 90th percentile.** If no candidates score > 0.75, Diamond uses the top 10% instead — the rails are always written, even if the fitness surface is flat.
- **Rails are written directly to the JSON file**, not via Redis — `_update_vault` reads and writes `hormonal_vault.json` synchronously. A concurrent Soul hot-reload could race with this write.
- **Training data is 24-hour window only.** Intraday regime shifts will dominate the training signal. A bad 24-hour period can produce overly tight or wrong rails.

---

## 9. Open Questions / Risks

- **GP fit on potentially 2–3 dimensions of real signal in 23-D space.** With only 50–500 synapse tickets covering a 23-D param space, the GP surface is extremely underfit. The rails may reflect noise more than signal.
- **No validation of rail correctness.** Rails are written without any cross-validation or out-of-sample check — the 5,000 test candidates are drawn from the same distribution as training.
- **Race condition with Soul vault reload.** Diamond writes `hormonal_vault.json` directly while Soul may be reading it via Redis bootstrap or `_check_vault_mutation()`.
- **`realized_fitness` definition is opaque here** — its quality entirely determines whether Diamond produces meaningful or misleading rails.
