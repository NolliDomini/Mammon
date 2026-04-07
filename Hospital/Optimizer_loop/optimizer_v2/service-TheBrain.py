from __future__ import annotations

import hashlib
import json
import math
from dataclasses import dataclass
from typing import Any, Dict, List

import numpy as np

from Hippocampus.Archivist.librarian import MultiTransportLibrarian, librarian
from Hospital.Optimizer_loop.bounds import MAXS, MINS, normalize_weights, PARAM_KEYS
from Hospital.Optimizer_loop.guardrailed_optimizer import GuardrailedOptimizer, ScoreVector


@dataclass
class V2Budget:
    edge_lhs_n: int = 64
    island_n: int = 12
    top_k: int = 6
    refine_lhs_n: int = 32
    bayes_n: int = 15
    min_support: int = 25
    diversity_floor: float = 0.05
    # Compatibility aliases used by legacy tests/spec docs.
    stage_c_n: int | None = None
    stage_f_n: int | None = None

    def __post_init__(self):
        if self.stage_c_n is not None:
            self.island_n = int(self.stage_c_n)
        if self.stage_f_n is not None:
            self.refine_lhs_n = int(self.stage_f_n)


from sklearn.gaussian_process import GaussianProcessRegressor
from sklearn.gaussian_process.kernels import Matern, ConstantKernel as C

from Hospital.Optimizer_loop.bounds import MAXS, MINS, normalize_weights, DOMAIN_SLICES


class OptimizerV2Engine:
    """
    Stage A-H optimizer pipeline with guardrailed scoring and promotion.
    Target #71: Supports 'Pause & Resume' state machine.
    Piece 209: Domain-aware optimization support.
    """

    def __init__(
        self,
        run_id: str,
        librarian: MultiTransportLibrarian = librarian,
        *,
        seed: int = 42,
        budget: V2Budget | None = None,
        domain: str = "ALL"
    ):
        self.run_id = run_id
        self.lib = librarian
        self.guard = GuardrailedOptimizer(run_id=run_id, librarian=librarian)
        self.seed = int(seed)
        self.rng = np.random.default_rng(self.seed)
        self.budget = budget or V2Budget()
        self.domain = domain.upper()
        
        # Piece 209: Load domain config if applicable
        self.domain_config = DOMAIN_SLICES.get(self.domain, {"indices": list(range(len(PARAM_KEYS)))})
        self.domain_indices = self.domain_config["indices"]
        
        # Target #71: Persistent State for Interleaving
        self.current_stage_group = "IDLE"
        self.stage_results: Dict[str, Any] = {}

    def run_stage_group(self, group: str, **kwargs) -> Dict[str, Any]:
        """
        Target #71: Interleaved entry point.
        Executes a specific group of stages and preserves context.
        """
        group = group.upper()
        regime_id = kwargs.get("regime_id", "UNK")
        price = float(kwargs.get("price", 0.0))
        atr = float(kwargs.get("atr", 0.0))
        stop_level = float(kwargs.get("stop_level", 0.0))
        mutations = kwargs.get("mutations")

        if group == "SCOUT":
            # Stages A-C: Exploration
            self.stage_results["scout"] = self.run_scout_pipeline(regime_id, price, atr, stop_level)
            self.current_stage_group = "SCOUT_COMPLETE"
            return {"status": "SCOUT_COMPLETE", "n_candidates": len(self.stage_results["scout"])}

        elif group == "PRIME":
            # Stages D-E: Grounding (Requires Scout results)
            scout_results = self.stage_results.get("scout", [])
            if not scout_results:
                return {"status": "ERROR", "reason": "PRIME_WITHOUT_SCOUT"}
            
            # Use T-distribution noise from Stage D
            shocks = self._stage_d_walk_context(regime_id, mu=0.0, sigma=atr)
            self.stage_results["grounded"] = self._stage_e_vectorized_monte(
                scout_results, regime_id, price, atr, stop_level, shocks
            )
            self.current_stage_group = "PRIME_COMPLETE"
            return {"status": "PRIME_COMPLETE", "n_grounded": len(self.stage_results["grounded"])}

        elif group == "CALCULATE":
            # Stages F-H: Exploitation & Promotion
            grounded = self.stage_results.get("grounded", [])
            if not grounded:
                return {"status": "ERROR", "reason": "CALCULATE_WITHOUT_PRIME"}
            
            refined = self._stage_f_refine_lhs(grounded, regime_id, price, atr, stop_level, mutations or [])
            top_candidates = self._stage_g_bayesian_exploit(refined, regime_id, allow_bayesian=True)
            
            if not top_candidates:
                return {"status": "ERROR", "reason": "GPR_FAILURE"}
                
            winner = sorted(top_candidates, key=lambda x: x["robust_score"], reverse=True)[0]
            promoted, reason = self._stage_h_promotion_gate(winner, top_candidates, regime_id=regime_id)
            
            # Reset Machine
            self.stage_results = {}
            self.current_stage_group = "IDLE"
            
            return {
                "status": "CALCULATE_COMPLETE",
                "promoted": promoted,
                "reason": reason,
                "winner_cid": winner["candidate_id"],
                "robust_score": winner["robust_score"]
            }

        return {"status": "ERROR", "reason": f"UNKNOWN_GROUP:{group}"}

    def run_scout_pipeline(self, regime_id: str, price: float, atr: float, stop_level: float) -> List[Dict[str, Any]]:
        # Encapsulates Stages A, B, C
        a_rows = self._stage_a_edge_lhs_scan(regime_id, price, atr, stop_level)
        b_rows = self._stage_b_island_fill(a_rows, regime_id, price, atr, stop_level)
        return b_rows

    def run_pipeline(
        self,
        *,
        regime_id: str,
        price: float,
        atr: float,
        stop_level: float,
        allow_bayesian: bool,
        mutations: List[float] | None = None,
    ) -> Dict[str, Any]:
        # Stage A
        a_rows = self._stage_a_edge_lhs(regime_id, price, atr, stop_level)
        if not a_rows:
            self.guard.log_stage_drop("stage_a_edge_lhs_scan", "EDGE_SCAN_EMPTY", regime_id=regime_id)
            return {"status": "skipped", "reason": "EDGE_SCAN_EMPTY"}

        # Stage B
        b_rows = self._stage_b_semi_middle_band(a_rows, regime_id)
        if not b_rows:
            self.guard.log_stage_drop("stage_b_band_extract", "BAND_EMPTY", regime_id=regime_id)
            return {"status": "skipped", "reason": "BAND_EMPTY"}

        # Stage C
        c_rows = self._stage_c_candidate_library_fill(b_rows, regime_id)
        if not c_rows:
            self.guard.log_stage_drop("stage_c_library_fill", "CANDIDATES_EMPTY", regime_id=regime_id)
            return {"status": "skipped", "reason": "CANDIDATES_EMPTY"}

        # Stage D
        d_mutations = self._stage_d_walk_context(regime_id, atr=atr, mutations=mutations)
        if not d_mutations:
            self.guard.log_stage_drop("stage_d_walk_context", "NO_MUTATIONS", regime_id=regime_id)
            return {"status": "skipped", "reason": "NO_MUTATIONS"}

        # Stage E
        e_rows = self._stage_e_vectorized_monte(c_rows, regime_id, price, atr, stop_level, d_mutations)
        if not e_rows:
            self.guard.log_stage_drop("stage_e_monte_scoring", "NO_SCORED_CANDIDATES", regime_id=regime_id)
            return {"status": "skipped", "reason": "NO_SCORED_CANDIDATES"}

        # Stage F
        f_rows = self._stage_f_refine_lhs(e_rows, regime_id, price, atr, stop_level, d_mutations)
        if not f_rows:
            self.guard.log_stage_drop("stage_f_refine_lhs", "REFINE_EMPTY", regime_id=regime_id)
            return {"status": "skipped", "reason": "REFINE_EMPTY"}

        # Stage G
        g_rows = self._stage_g_bayesian_exploit(f_rows, regime_id, allow_bayesian=allow_bayesian)
        ranked = sorted((g_rows if g_rows else f_rows), key=lambda x: x["robust_score"], reverse=True)
        winner = ranked[0]

        # Stage H
        promoted, reason = self._stage_h_promotion_gate(winner, ranked, regime_id=regime_id)

        return {
            "status": "ok",
            "winner_candidate_id": winner["candidate_id"],
            "winner_robust_score": float(winner["robust_score"]),
            "promoted": bool(promoted),
            "promotion_reason": reason,
            "candidates_scored": len(e_rows),
        }

    def _stage_a_edge_lhs(self, regime_id: str, price: float, atr: float, stop_level: float) -> List[Dict[str, Any]]:
        stage = "stage_a_edge_lhs_scan"
        self.guard.log_stage_start(stage, regime_id=regime_id)
        rows = self._sample_rows(self.budget.edge_lhs_n)
        output: List[Dict[str, Any]] = []
        for row in rows:
            row = self._sanitize_row(row)
            approx = self._approx_score(row, price, atr, stop_level)
            if approx >= 0.35:
                output.append({"row": row, "approx_score": approx})
        self.guard.log_stage_complete(stage, regime_id=regime_id, metrics={"n_edges": len(output)})
        return output

    def _stage_b_semi_middle_band(self, a_rows: List[Dict[str, Any]], regime_id: str) -> List[Dict[str, Any]]:
        stage = "stage_b_band_extract"
        self.guard.log_stage_start(stage, regime_id=regime_id)
        ordered = sorted(a_rows, key=lambda x: x["approx_score"], reverse=True)
        if not ordered:
            self.guard.log_stage_complete(stage, regime_id=regime_id, metrics={"n_band": 0})
            return []
        lo = max(1, int(len(ordered) * 0.2))
        hi = max(lo + 1, int(len(ordered) * 0.8))
        band = ordered[lo:hi]
        self.guard.log_stage_complete(stage, regime_id=regime_id, metrics={"n_band": len(band)})
        return band

    def _stage_c_candidate_library_fill(self, b_rows: List[Dict[str, Any]], regime_id: str) -> List[Dict[str, Any]]:
        stage = "stage_c_library_fill"
        self.guard.log_stage_start(stage, regime_id=regime_id)
        top = sorted(b_rows, key=lambda x: x["approx_score"], reverse=True)[: self.budget.top_k]
        islands: List[Dict[str, Any]] = []
        distances: List[float] = []
        centroid = np.mean(np.vstack([t["row"] for t in top]), axis=0) if top else np.zeros(len(PARAM_KEYS))

        for parent in top:
            p_row = parent["row"]
            noise = self.rng.normal(0.0, (MAXS - MINS) * 0.02, size=(self.budget.island_n, len(PARAM_KEYS)))
            cluster = p_row + noise
            for row in cluster:
                row = self._sanitize_row(row)
                cid = self._candidate_id(row, regime_id, stage)
                dist = float(np.linalg.norm((row - centroid) / (MAXS - MINS + 1e-9)))
                distances.append(dist)
                self.guard.register_candidate(
                    cid,
                    stage,
                    self._row_to_params(row),
                    regime_id=regime_id,
                    diversity_dist=dist,
                    support_count=0,
                    kept=True,
                )
                islands.append({"candidate_id": cid, "row": row})

        self._write_diversity(stage_name=stage, distances=distances, scores=[])
        self.guard.log_stage_complete(stage, regime_id=regime_id, metrics={"n_islands": len(islands)})
        return islands

    def _stage_d_walk_context(
        self,
        regime_id: str,
        *,
        atr: float | None = None,
        mutations: List[float] | None = None,
        mu: float | None = None,
        sigma: float | None = None,
    ) -> List[float]:
        """
        Unified Stage D contract.
        Supports live mutations (run_pipeline) and PRIME shock generation (run_stage_group).
        """
        stage = "stage_d_walk_context"
        self.guard.log_stage_start(stage, regime_id=regime_id)

        if mutations:
            out = [float(x) for x in mutations]
            self.guard.log_stage_complete(stage, regime_id=regime_id, metrics={"mutation_count": len(out)})
            return out

        if sigma is not None:
            # Fat-tail fallback used by PRIME interleave path.
            df_tail = 3.0
            n_steps = 256
            noise = self.rng.standard_t(df=df_tail, size=(1000, n_steps)) * float(sigma) + float(mu or 0.0)
            out = noise.flatten().tolist()
            self.guard.log_stage_complete(stage, regime_id=regime_id, metrics={"mutation_count": len(out)})
            return out

        sigma_fallback = max(float(atr or 0.0) * 0.05, 1e-6)
        out = self.rng.normal(0.0, sigma_fallback, size=self.budget.min_support * 60).tolist()
        self.guard.log_stage_complete(stage, regime_id=regime_id, metrics={"mutation_count": len(out)})
        return out

    def _stage_e_vectorized_monte(
        self,
        rows: List[Dict[str, Any]],
        regime_id: str,
        price: float,
        atr: float,
        stop_level: float,
        mutations: List[float],
    ) -> List[Dict[str, Any]]:
        stage = "stage_e_monte_scoring"
        self.guard.log_stage_start(stage, regime_id=regime_id)
        if not mutations:
            return []

        # 1. Setup Data Structures
        candidates = np.vstack([r["row"] for r in rows])
        n_candidates = len(candidates)
        n_steps = 60
        n_paths = len(mutations) // n_steps
        if n_paths < self.budget.min_support:
            return []
        
        # [paths, steps]
        shocks = np.array(mutations[: n_paths * n_steps]).reshape(n_paths, n_steps)
        
        # 2. Extract Candidate Parameters (Vectorized)
        # Gear: Index 0, Noise: Index 1, StopMult: Index 21
        gears = np.round(candidates[:, 0]).astype(int)
        gears = np.clip(gears, 1, n_steps)
        noise_scalars = candidates[:, 1].reshape(-1, 1, 1) # [cand, 1, 1]
        stop_mults = candidates[:, 21].reshape(-1, 1) # [cand, 1]
        
        # 3. Vectorized Path Generation
        # BroadCast: [cand, paths, steps]
        # Cumulative shocks for all candidates and paths
        path_shocks = shocks.reshape(1, n_paths, n_steps) * noise_scalars
        paths = price + np.cumsum(path_shocks, axis=2)
        
        # 4. Survival Scoring (Worst, Neutral, Best)
        stop_floors = price - (atr * stop_mults) # [cand, 1]
        dist_to_stop = -(atr * stop_mults) # [cand, 1] - Distance is negative for stop-loss
        
        # Piece 14: Use central standardized kernel for consistent Risk Gate enforcement
        from Hospital.Optimizer_loop.bounds import calculate_batch_fitness
        
        # Calculate min reach relative to start (0.0) for the kernel
        # min_reach_rel: [cand, paths]
        masked_rel = np.where(gear_mask_3d, np.cumsum(path_shocks, axis=2), 999.0)
        min_reach_rel = np.min(masked_rel, axis=2) # [cand, paths]
        
        # Standard Neutral Lane (1.0x noise)
        neutral_survivals = np.mean(min_reach_rel > dist_to_stop, axis=1) # [cand]
        
        # Worst Lane (2.0x noise)
        worst_masked_rel = np.where(gear_mask_3d, np.cumsum(shocks.reshape(1, n_paths, n_steps) * (noise_scalars * 2.0), axis=2), 999.0)
        worst_survivals = np.mean(np.min(worst_masked_rel, axis=2) > dist_to_stop, axis=1)
        
        # Best Lane (0.5x noise)
        best_masked_rel = np.where(gear_mask_3d, np.cumsum(shocks.reshape(1, n_paths, n_steps) * (noise_scalars * 0.5), axis=2), 999.0)
        best_survivals = np.mean(np.min(best_masked_rel, axis=2) > dist_to_stop, axis=1)
        
        # 5. Expectancy & Stability
        # Terminal price at the end of the gear
        terminal_prices = np.zeros((n_candidates, n_paths))
        for i in range(n_candidates):
            terminal_prices[i] = paths[i, :, gears[i]-1]
            
        expectancies = np.mean(terminal_prices - price, axis=1) / (price * 0.01 + 1e-9)
        stabilities = 1.0 - np.std([worst_survivals, neutral_survivals, best_survivals], axis=0)
        
        # 6. Final Integration
        scores: List[Dict[str, Any]] = []
        for i in range(n_candidates):
            # Weighted Risk Score using candidate's own weights (Indices 2, 3, 4)
            weighted_risk = (candidates[i, 2] * worst_survivals[i]) + \
                            (candidates[i, 3] * neutral_survivals[i]) + \
                            (candidates[i, 4] * best_survivals[i])
            
            # Apply Risk Gate logic from central kernel
            # (If score <= 0.5, we slash it)
            gated_score = weighted_risk if weighted_risk > 0.5 else weighted_risk * 0.5

            vec = ScoreVector(
                expectancy=float(np.clip(0.5 + expectancies[i], 0, 1)),
                survival=float(neutral_survivals[i]),
                stability=float(stabilities[i]),
                drawdown=float(1.0 - worst_survivals[i]),
                uncertainty=float(1.0 / math.sqrt(n_paths)),
                slippage_cost=float(candidates[i, 18] * 0.4),
                score_std=float(np.std([worst_survivals[i], neutral_survivals[i], best_survivals[i]])),
            )
            final_score, robust_score = self.guard.compute_scores(rows[i]["candidate_id"], vec)
            
            # Penalize robust_score if gated_score was slashed
            if weighted_risk <= 0.5:
                robust_score *= 0.5

            scores.append({
                **rows[i],
                "final_score": float(final_score),
                "robust_score": float(robust_score),
                "survival": float(neutral_survivals[i]),
                "stability": float(stabilities[i]),
                "drawdown": float(1.0 - worst_survivals[i]),
                "slippage_adj": float(1.0 - (candidates[i, 18] * 0.5)),
                "support_count": int(n_paths),
            })

        self.lib.write_regime_coverage(
            run_id=self.run_id,
            regime_id=regime_id,
            candidate_count=n_candidates,
            support_count=int(n_paths * n_candidates),
        )

        self._write_diversity(stage_name=stage, distances=[0.0], scores=[r["robust_score"] for r in scores])
        self.guard.log_stage_complete(stage, regime_id=regime_id, metrics={"n_scored": len(scores)})
        return scores

    def _stage_f_refine_lhs(
        self,
        e_rows: List[Dict[str, Any]],
        regime_id: str,
        price: float,
        atr: float,
        stop_level: float,
        mutations: List[float],
    ) -> List[Dict[str, Any]]:
        stage = "stage_f_refine_lhs"
        self.guard.log_stage_start(stage, regime_id=regime_id)
        best = sorted(e_rows, key=lambda x: x["robust_score"], reverse=True)[0]
        lo = np.maximum(MINS, best["row"] - (MAXS - MINS) * 0.05)
        hi = np.minimum(MAXS, best["row"] + (MAXS - MINS) * 0.05)
        u = self.rng.uniform(0.0, 1.0, size=(self.budget.refine_lhs_n, len(PARAM_KEYS)))
        rows = lo + u * (hi - lo)

        refined = []
        for row in rows:
            row = self._sanitize_row(row)
            cid = self._candidate_id(row, regime_id, stage)
            self.guard.register_candidate(cid, stage, self._row_to_params(row), regime_id=regime_id, kept=True)
            refined.append({"candidate_id": cid, "row": row})

        scored = self._stage_e_vectorized_monte(refined, regime_id, price, atr, stop_level, mutations)
        self.guard.log_stage_complete(stage, regime_id=regime_id, metrics={"n_refined": len(scored)})
        return scored

    def _stage_g_bayesian_exploit(self, f_rows: List[Dict[str, Any]], regime_id: str, allow_bayesian: bool) -> List[Dict[str, Any]]:
        stage = "stage_g_bayesian_exploit"
        if not allow_bayesian:
            self.guard.log_stage_drop(stage, "BAYESIAN_SKIP_CADENCE", regime_id=regime_id)
            return []

        self.guard.log_stage_start(stage, regime_id=regime_id)
        
        # Phase 8 Target: Implement true GP Regression
        x_train = np.array([r["row"] for r in f_rows])
        y_train = np.array([float(r["robust_score"]) for r in f_rows])
        
        if len(x_train) < 5:
            self.guard.log_stage_drop(stage, "INSUFFICIENT_TRAINING_DATA", regime_id=regime_id)
            return []

        # Define Kernel (Matern 5/2 is standard for smooth yet bumpy trading landscapes)
        kernel = C(1.0, (1e-3, 1e3)) * Matern(length_scale=1.0, length_scale_bounds=(1e-2, 1e2), nu=2.5)
        gp = GaussianProcessRegressor(kernel=kernel, n_restarts_optimizer=10, random_state=self.seed)
        
        try:
            gp.fit(x_train, y_train)
            
            # Acquisition: Identify peak through L-BFGS-B (Standard in GPR)
            # For simplicity in this piece, we scout 1000 uniform candidates and pick the best predicted.
            try:
                x_scout = self._sample_rows(1000)
            except Exception as e:
                # [HOSP-E-P84-805] Sampling failure
                print(f"[HOSP-E-P84-805] FURNACE: Candidate sampling failed: {e}")
                self.guard.log_stage_drop(stage, "SAMPLING_FAILURE", regime_id=regime_id)
                return []

            y_pred, sigma = gp.predict(x_scout, return_std=True)
            
            # Acquisition Function: Expected Improvement (Simplified to Upper Confidence Bound)
            # kappa=1.96 for 95% confidence interval
            ucb = y_pred + (1.96 * sigma)
            best_idx = np.argmax(ucb)
            
            bayes_row = self._sanitize_row(x_scout[best_idx])
            cid = self._candidate_id(bayes_row, regime_id, stage)
            
            # Record diagnostic
            self.lib.write_bayesian_diagnostic(
                run_id=self.run_id,
                candidate_id=cid,
                mu=float(y_pred[best_idx]),
                sigma=float(sigma[best_idx]),
                acquisition=float(ucb[best_idx]),
                effective_sample_size=float(len(x_train))
            )
            
            # Create the Bayesian Winner candidate
            bayes_candidate = {
                "candidate_id": cid,
                "row": bayes_row,
                "robust_score": float(y_pred[best_idx]),
                "support_count": int(f_rows[0].get("support_count", 0)),
                "survival": float(f_rows[0].get("survival", 0.0)),
                "stability": float(f_rows[0].get("stability", 0.0)),
                "drawdown": float(f_rows[0].get("drawdown", 1.0)),
                "slippage_adj": float(f_rows[0].get("slippage_adj", 0.0)),
            }
            
            top = sorted(f_rows, key=lambda x: x["robust_score"], reverse=True)[:self.budget.bayes_n]
            top.append(bayes_candidate)
            
            self.guard.log_stage_complete(stage, regime_id=regime_id, metrics={"n_bayes": len(top)})
            return top
            
        except Exception as e:
            # [HOSP-E-P84-804] Stage execution failure (GPR fit)
            print(f"[HOSP-E-P84-804] FURNACE: GPR Fit failed: {e}")
            self.guard.log_stage_drop(stage, "GPR_FIT_FAILURE", regime_id=regime_id)
            return []

    def _stage_h_promotion_gate(self, winner: Dict[str, Any], ranked: List[Dict[str, Any]], *, regime_id: str) -> tuple[bool, str]:
        stage = "stage_h_promotion_gate"
        self.guard.log_stage_start(stage, regime_id=regime_id)
        min_distance = self._min_pairwise_distance([r["row"] for r in ranked[: min(len(ranked), 8)]])
        self._write_diversity(stage_name=stage, distances=[min_distance], scores=[r["robust_score"] for r in ranked[:8]])

        if min_distance < float(self.budget.diversity_floor):
            self.lib.write_promotion_decision(
                run_id=self.run_id,
                candidate_id=winner["candidate_id"],
                decision="kept_prior",
                reason_code="PROMOTION_FAIL_DIVERSITY",
                score=float(winner.get("robust_score", 0.0)),
                drawdown=float(winner.get("drawdown", 1.0)),
                stability=float(winner.get("stability", 0.0)),
                slippage_adj=float(winner.get("slippage_adj", 0.0)),
                support_count=int(winner.get("support_count", 0)),
                drift=0.05,
            )
            self.guard.log_stage_complete(
                stage,
                regime_id=regime_id,
                metrics={"promoted": False, "reason": "PROMOTION_FAIL_DIVERSITY", "min_distance": float(min_distance)},
            )
            return False, "PROMOTION_FAIL_DIVERSITY"

        promoted, reason = self.guard.promotion_decision(
            winner["candidate_id"],
            score=float(winner.get("robust_score", 0.0)),
            drawdown=float(winner.get("drawdown", 1.0)),
            stability=float(winner.get("stability", 0.0)),
            slippage_adj=float(winner.get("slippage_adj", 0.0)),
            support_count=int(winner.get("support_count", 0)),
            drift=0.05,
            diversity=min_distance,
        )
        self.guard.log_stage_complete(
            stage,
            regime_id=regime_id,
            metrics={"promoted": bool(promoted), "reason": reason, "min_distance": float(min_distance)},
        )
        return promoted, reason

    def _sample_rows(self, n: int) -> np.ndarray:
        """Piece 211/216: Sample rows constrained to domain slice + Diamond rails."""
        # 1. Start with current Gold as baseline for all rows
        vault = self.lib.get_hormonal_vault()
        gold_params = vault.get("gold", {}).get("params", {})
        rails = vault.get("diamond_rails", {}).get("bounds", {})
        
        # If Gold is missing, use median of MINS/MAXS as safe baseline
        if not gold_params:
            baseline_vec = (MINS + MAXS) / 2.0
        else:
            baseline_vec = np.array([float(gold_params.get(k, (MINS[i]+MAXS[i])/2.0)) for i, k in enumerate(PARAM_KEYS)])
            
        rows = np.tile(baseline_vec, (n, 1))
        
        # 2. Randomize only the domain indices
        # Piece 216: Use Diamond Rails if available, else fall back to MINS/MAXS
        low = np.array([float(rails.get(k, {"min": MINS[i]})["min"]) for i, k in enumerate(PARAM_KEYS)])
        high = np.array([float(rails.get(k, {"max": MAXS[i]})["max"]) for i, k in enumerate(PARAM_KEYS)])
        
        # Only randomized the domain indices
        domain_low = low[self.domain_indices]
        domain_high = high[self.domain_indices]
        u = self.rng.uniform(0.0, 1.0, size=(n, len(self.domain_indices)))
        
        rows[:, self.domain_indices] = domain_low + u * (domain_high - domain_low)
        return rows

    def _sanitize_row(self, row: np.ndarray) -> np.ndarray:
        row = np.clip(row, MINS, MAXS)
        row = normalize_weights(row)
        row[0] = float(int(round(row[0])))
        return row

    def _candidate_id(self, row: np.ndarray, regime_id: str, stage: str) -> str:
        payload = f"{regime_id}|{stage}|{','.join(f'{x:.8f}' for x in row.tolist())}"
        return hashlib.sha1(payload.encode("utf-8")).hexdigest()[:20]

    def _approx_score(self, row: np.ndarray, price: float, atr: float, stop_level: float) -> float:
        """
        Piece 12: Consolidated indicator authority.
        Delegates core scoring math to the Council's Numba-accelerated kernels.
        """
        from Cerebellum.council.utils.math_kernels import calculate_approx_fitness_njit
        
        # 1. Prepare inputs
        risk_tilt = float(row[2] * 0.2 + row[3] * 0.4 + row[4] * 0.4)
        balance = 1.0 - abs(row[5] - row[8]) # Council weights balance
        distance = abs(price - stop_level) / max(atr, 1e-6)
        
        # 2. Delegate to centralized authority
        return calculate_approx_fitness_njit(risk_tilt, balance, distance)

    def _row_to_params(self, row: np.ndarray) -> Dict[str, float]:
        return {k: float(v) for k, v in zip(PARAM_KEYS, row.tolist())}

    def _min_pairwise_distance(self, rows: List[np.ndarray]) -> float:
        if len(rows) < 2:
            return 1.0
        norm = MAXS - MINS + 1e-9
        best = float("inf")
        for i in range(len(rows)):
            for j in range(i + 1, len(rows)):
                d = float(np.linalg.norm((rows[i] - rows[j]) / norm))
                if d < best:
                    best = d
        return float(best if np.isfinite(best) else 0.0)

    def _write_diversity(self, *, stage_name: str, distances: List[float], scores: List[float]):
        if scores:
            vals = np.array(scores, dtype=float)
            p = np.abs(vals) + 1e-9
            p = p / np.sum(p)
            entropy = float(-np.sum(p * np.log(p)))
            coverage = float(np.mean(vals > np.median(vals)))
        else:
            entropy = 0.0
            coverage = 0.0
        min_distance = float(min(distances)) if distances else 0.0
        self.lib.write_diversity_metric(
            run_id=self.run_id,
            stage_name=stage_name,
            entropy=entropy,
            coverage=coverage,
            min_distance=min_distance,
        )
