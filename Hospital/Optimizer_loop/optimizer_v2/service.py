from __future__ import annotations

import hashlib
import json
import math
from dataclasses import dataclass
from typing import Any, Dict, List

import numpy as np

from Hippocampus.Archivist.optimizer_librarian import OptimizerLibrarian
from Hospital.Optimizer_loop.bounds import MAXS, MINS, normalize_weights
from Hospital.Optimizer_loop.guardrailed_optimizer import GuardrailedOptimizer, ScoreVector


PARAM_KEYS = [
    "active_gear",
    "monte_noise_scalar",
    "monte_w_worst",
    "monte_w_neutral",
    "monte_w_best",
    "council_w_atr",
    "council_w_adx",
    "council_w_vol",
    "council_w_vwap",
    "gatekeeper_min_monte",
    "gatekeeper_min_council",
    "callosum_w_monte",
    "callosum_w_right",
    "callosum_w_adx",
    "callosum_w_weak",
    "brain_stem_w_turtle",
    "brain_stem_w_council",
    "brain_stem_survival",
    "brain_stem_noise",
    "brain_stem_sigma",
    "brain_stem_bias",
    "stop_loss_mult",
    "breakeven_mult",
]


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


class OptimizerV2Engine:
    """
    Stage A-H optimizer pipeline with guardrailed scoring and promotion.
    """

    def __init__(
        self,
        run_id: str,
        librarian: OptimizerLibrarian,
        *,
        seed: int = 42,
        budget: V2Budget | None = None,
    ):
        self.run_id = run_id
        self.lib = librarian
        self.guard = GuardrailedOptimizer(run_id=run_id, librarian=librarian)
        self.seed = int(seed)
        self.rng = np.random.default_rng(self.seed)
        self.budget = budget or V2Budget()

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

    def _stage_d_walk_context(self, regime_id: str, *, atr: float, mutations: List[float] | None) -> List[float]:
        stage = "stage_d_walk_context"
        self.guard.log_stage_start(stage, regime_id=regime_id)
        if mutations:
            out = [float(x) for x in mutations]
        else:
            # Deterministic fallback for environments without walk mutations yet.
            sigma = max(float(atr) * 0.05, 1e-6)
            out = self.rng.normal(0.0, sigma, size=self.budget.min_support * 60).tolist()
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

        candidates = np.vstack([r["row"] for r in rows])
        n_steps = 60
        n_paths = len(mutations) // n_steps
        if n_paths < self.budget.min_support:
            return []
        shocks = np.array(mutations[: n_paths * n_steps]).reshape(n_paths, n_steps)

        scores: List[Dict[str, Any]] = []
        for i, cand in enumerate(candidates):
            gear = max(1, min(int(round(cand[0])), n_steps))
            noise_scalar = float(cand[1])
            stop_mult = float(cand[21])

            scaled = price + np.cumsum(shocks * noise_scalar, axis=1)
            min_reach = np.min(scaled[:, :gear], axis=1)
            stop_floor = price - (atr * stop_mult)

            worst = np.mean((price + np.min(np.cumsum(shocks * noise_scalar * 2.0, axis=1)[:, :gear], axis=1)) > stop_floor)
            neutral = np.mean(min_reach > stop_floor)
            best = np.mean((price + np.min(np.cumsum(shocks * noise_scalar * 0.5, axis=1)[:, :gear], axis=1)) > stop_floor)

            stability = float(1.0 - np.std([worst, neutral, best]))
            terminal = price + np.sum(shocks[:, :gear], axis=1)
            expectancy = float(np.mean(terminal - price) / (price * 0.01 + 1e-9))
            vec = ScoreVector(
                expectancy=float(np.clip(0.5 + expectancy, 0, 1)),
                survival=float(neutral),
                stability=stability,
                drawdown=float(1.0 - worst),
                uncertainty=float(1.0 / math.sqrt(n_paths)),
                slippage_cost=float(cand[18] * 0.4),
                score_std=float(np.std([worst, neutral, best])),
            )
            final_score, robust_score = self.guard.compute_scores(rows[i]["candidate_id"], vec)

            self.lib.write_regime_coverage(
                run_id=self.run_id,
                regime_id=regime_id,
                candidate_count=1,
                support_count=int(n_paths),
            )
            scores.append(
                {
                    **rows[i],
                    "final_score": float(final_score),
                    "robust_score": float(robust_score),
                    "survival": float(neutral),
                    "stability": stability,
                    "drawdown": float(1.0 - worst),
                    "slippage_adj": float(1.0 - (cand[18] * 0.5)),
                    "support_count": int(n_paths),
                }
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
        top = sorted(f_rows, key=lambda x: x["robust_score"], reverse=True)[: self.budget.bayes_n]
        if not top:
            self.guard.log_stage_complete(stage, regime_id=regime_id, metrics={"n_bayes": 0})
            return []

        scores = np.array([max(1e-9, float(r["robust_score"])) for r in top])
        weights = scores / np.sum(scores)
        mat = np.vstack([r["row"] for r in top])
        bayes_row = self._sanitize_row(np.average(mat, axis=0, weights=weights))
        cid = self._candidate_id(bayes_row, regime_id, stage)
        diag_sigma = float(np.std(scores))
        self.lib.write_bayesian_diagnostic(
            run_id=self.run_id,
            candidate_id=cid,
            mu=float(np.mean(scores)),
            sigma=diag_sigma,
            acquisition=float(np.max(scores)),
            effective_sample_size=float(1.0 / np.sum(weights ** 2)),
        )
        top.append(
            {
                "candidate_id": cid,
                "row": bayes_row,
                "robust_score": float(np.max(scores) * 1.05),
                "support_count": int(top[0].get("support_count", 0)),
                "survival": float(top[0].get("survival", 0.0)),
                "stability": float(top[0].get("stability", 0.0)),
                "drawdown": float(top[0].get("drawdown", 1.0)),
                "slippage_adj": float(top[0].get("slippage_adj", 0.0)),
            }
        )
        self.guard.log_stage_complete(stage, regime_id=regime_id, metrics={"n_bayes": len(top)})
        return top

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
        u = self.rng.uniform(0.0, 1.0, size=(n, len(PARAM_KEYS)))
        return MINS + u * (MAXS - MINS)

    def _sanitize_row(self, row: np.ndarray) -> np.ndarray:
        row = np.clip(row, MINS, MAXS)
        row = normalize_weights(row)
        row[0] = float(int(round(row[0])))
        return row

    def _candidate_id(self, row: np.ndarray, regime_id: str, stage: str) -> str:
        payload = f"{regime_id}|{stage}|{','.join(f'{x:.8f}' for x in row.tolist())}"
        return hashlib.sha1(payload.encode("utf-8")).hexdigest()[:20]

    def _approx_score(self, row: np.ndarray, price: float, atr: float, stop_level: float) -> float:
        risk_tilt = float(row[2] * 0.2 + row[3] * 0.4 + row[4] * 0.4)
        balance = 1.0 - abs(row[5] - row[8])
        distance = abs(price - stop_level) / max(atr, 1e-6)
        penalty = min(distance * 0.03, 0.30)
        score = np.clip((0.55 * risk_tilt) + (0.35 * balance) - penalty, 0.0, 1.0)
        return float(score)

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
