# Deep Dive: GuardrailedOptimizer — Scoring & Promotion Gate

## 1. Purpose & Role
GuardrailedOptimizer is the **scoring engine and promotion gate** for the Hospital optimizer pipeline. It does not run optimization itself — it provides the structured scaffolding that the optimizer stages (A–H in `optimizer_v2`) use to:
1. Score candidates via a 6-component weighted formula
2. Apply a multi-threshold promotion gate with reason-coded audit trail
3. Log every stage transition and decision to DuckDB for forensic replay

It is a **component used by** the optimizer, not a standalone loop.

---

## 2. When Does It Run?

Instantiated and called by `optimizer_v2/service.py` during each optimization run. Not called from the live Soul pulse loop — Hospital-only path.

---

## 3. Score Formula

```
final_score = (
    0.28 × expectancy
  + 0.24 × survival
  + 0.20 × stability
  - 0.12 × drawdown
  - 0.08 × uncertainty
  - 0.08 × slippage_cost
)

robust_score = final_score - (robust_k × score_std)
```

Default weights are hard-coded in `__init__` but overridable at construction. `robust_k` defaults to 1.0 — subtracting one standard deviation of cross-regime scores penalizes candidates that are high-mean but inconsistent.

**Both scores are returned** and written to DuckDB. The optimizer stages decide which to use for ranking — typically `robust_score` is the gating signal.

---

## 4. ScoreVector — The 7-D Input

| Field | Sign | Meaning |
|---|---|---|
| `expectancy` | + | Expected return proxy |
| `survival` | + | Monte Carlo survival rate |
| `stability` | + | Cross-regime score consistency |
| `drawdown` | − | Max peak-to-trough decline |
| `uncertainty` | − | GP prediction uncertainty / variance |
| `slippage_cost` | − | Execution cost estimate |
| `score_std` | (robust) | Std dev of scores across regimes |

---

## 5. Promotion Gate — 7 Sequential Checks

`promotion_decision()` evaluates thresholds in order, returns on first failure:

| Check | Default Threshold | Failure Code |
|---|---|---|
| `score >= min_score` | 0.50 | `PROMOTION_FAIL_SCORE` |
| `drawdown <= max_drawdown` | 0.20 | `PROMOTION_FAIL_DRAWDOWN` |
| `stability >= min_stability` | 0.55 | `PROMOTION_FAIL_STABILITY` |
| `slippage_adj >= min_slippage_adj` | 0.45 | `PROMOTION_FAIL_SLIPPAGE_ADJ` |
| `support_count >= min_support` | 100 | `PROMOTION_FAIL_SUPPORT` |
| `drift <= max_drift` | 0.25 | `PROMOTION_FAIL_DRIFT` |
| `diversity >= min_diversity` | 0.0 | `PROMOTION_FAIL_DIVERSITY` |

All thresholds are set on `PromotionThresholds` at construction — overridable per run.

**First failure wins** — a candidate with score=0.49 is rejected at the score check and the remaining checks are skipped.

---

## 6. Audit Trail — DuckDB Writes

Every action writes to DuckDB via `OptimizerLibrarian` (a thin alias for `MultiTransportLibrarian`):

| Method | Table | What it records |
|---|---|---|
| `log_stage_start/complete/drop` | `optimizer_stage_runs` | Stage lifecycle events with metrics JSON |
| `register_candidate` | `candidate_library` | Param set, regime, diversity, keep/drop |
| `compute_scores` | `score_components` | All 7 score dimensions per candidate |
| `promotion_decision` | `promotion_decisions` | Gate outcome + reason code |

This creates a complete forensic record: every candidate ever evaluated, its scores, and why it passed or failed.

---

## 7. Dependencies

| Dependency | Direction | Purpose |
|---|---|---|
| `OptimizerLibrarian` | outbound | All DuckDB audit writes |
| `optimizer_v2/service.py` | inbound | Calls scoring + gate methods |
| DuckDB optimizer tables | write | Persistent audit trail |

---

## 8. Non-Obvious Behavior

- **`min_diversity` defaults to 0.0** — the diversity check never fails unless explicitly tightened. It is effectively disabled by default, meaning the optimizer does not enforce parameter diversity in the default configuration.
- **`robust_k=1.0` means the penalty equals one full standard deviation.** A candidate scoring 0.60 with std=0.15 has a robust_score of 0.45 — which fails the 0.50 `min_score` gate. Candidates with high cross-regime variance are quietly rejected by the robust score, even if their mean score is above threshold.
- **Score weights are not normalized to sum to 1.** Positive weights sum to 0.72 (0.28+0.24+0.20), negative weights sum to 0.28. `final_score` is not bounded to [0,1] — it can exceed 1.0 if component scores are high, or go negative if costs dominate.
- **`OptimizerLibrarian` is just `MultiTransportLibrarian`.** No additional logic — it's a naming alias so optimizer code can import a semantically meaningful class name without depending on the full librarian hierarchy.
- **Promotion writes `"kept_prior"` on failure**, not `"rejected"`. This naming suggests the intent: failed candidates are not discarded but retained in the candidate library for potential future reference.

---

## 9. Open Questions / Risks

- **Score component definitions are not standardized.** `expectancy`, `survival`, `stability` are passed in from the optimizer stages — their exact computation is in `optimizer_v2`, not here. GuardrailedOptimizer trusts whatever floats it receives. If a stage miscalculates a component, the gate passes silently.
- **`support_count >= 100` is a hard minimum.** For low-liquidity symbols or short replay windows, a candidate may never reach 100 supporting Monte Carlo paths — it is always rejected regardless of score quality.
- **No feedback from promotion back to optimizer.** `promotion_decision` returns `(bool, reason_code)` — the optimizer can ignore both. The audit trail records what happened, but enforcement depends entirely on the caller.
