import json
from dataclasses import dataclass
from typing import Dict, Tuple

from Hippocampus.Archivist.librarian import MultiTransportLibrarian, librarian


@dataclass
class ScoreVector:
    expectancy: float
    survival: float
    stability: float
    drawdown: float
    uncertainty: float
    slippage_cost: float
    score_std: float


@dataclass
class PromotionThresholds:
    min_score: float = 0.50
    max_drawdown: float = 0.20
    min_stability: float = 0.55
    min_slippage_adj: float = 0.45
    min_support: int = 100
    max_drift: float = 0.25
    min_diversity: float = 0.0


class GuardrailedOptimizer:
    """
    Stage scaffolding + component-scoring + promotion gate with reason-coded audit trail.
    V5: Audit logging delegated to Amygdala (Hippocampus) to prevent Logic Drift.
    """

    def __init__(
        self,
        run_id: str,
        librarian: MultiTransportLibrarian = librarian,
        *,
        weights: Dict[str, float] = None,
        robust_k: float = 1.0,
        thresholds: PromotionThresholds = None,
    ):
        self.run_id = run_id
        self.lib = librarian
        
        # Piece 162: Initialize the State-Scribe authority
        from Hippocampus.amygdala.service import Amygdala
        self.amygdala = Amygdala(librarian_instance=self.lib)

        self.weights = weights or {
            "expectancy": 0.28,
            "survival": 0.24,
            "stability": 0.20,
            "drawdown": 0.12,
            "uncertainty": 0.08,
            "slippage_cost": 0.08,
        }
        self.robust_k = float(robust_k)
        self.thresholds = thresholds or PromotionThresholds()

    def setup_schema(self):
        """Piece 100/101: Migration shim. Librarian handles schema initialization."""
        pass

    def log_stage_start(self, stage_name: str, regime_id: str = ""):
        self.amygdala.log_stage_run(self.run_id, stage_name, "STARTED", regime_id=regime_id)

    def log_stage_complete(self, stage_name: str, regime_id: str = "", metrics: Dict = None):
        self.amygdala.log_stage_run(self.run_id, stage_name, "COMPLETED", regime_id=regime_id, metrics=metrics)

    def log_stage_drop(self, stage_name: str, reason_code: str, regime_id: str = "", metrics: Dict = None):
        self.amygdala.log_stage_run(
            self.run_id,
            stage_name,
            "DROPPED",
            regime_id=regime_id,
            metrics=metrics,
            reason_code=reason_code,
        )

    def register_candidate(
        self,
        candidate_id: str,
        source_stage: str,
        params: Dict,
        regime_id: str = "",
        diversity_dist: float = 0.0,
        support_count: int = 0,
        kept: bool = True,
        reason_code: str = "",
    ):
        self.amygdala.register_candidate(
            run_id=self.run_id,
            candidate_id=candidate_id,
            source_stage=source_stage,
            params=params,
            regime_id=regime_id,
            diversity_dist=diversity_dist,
            support_count=support_count,
            kept=kept,
            reason_code=reason_code,
        )

    def compute_scores(self, candidate_id: str, vec: ScoreVector) -> Tuple[float, float]:
        final_score = (
            self.weights["expectancy"] * vec.expectancy
            + self.weights["survival"] * vec.survival
            + self.weights["stability"] * vec.stability
            - self.weights["drawdown"] * vec.drawdown
            - self.weights["uncertainty"] * vec.uncertainty
            - self.weights["slippage_cost"] * vec.slippage_cost
        )
        robust_score = final_score - (self.robust_k * vec.score_std)
        self.lib.write_score_components(
            self.run_id,
            candidate_id,
            expectancy=vec.expectancy,
            survival=vec.survival,
            stability=vec.stability,
            drawdown=vec.drawdown,
            uncertainty=vec.uncertainty,
            slippage_cost=vec.slippage_cost,
            final_score=final_score,
            robust_score=robust_score,
        )
        return final_score, robust_score

    def promotion_decision(
        self,
        candidate_id: str,
        *,
        score: float,
        drawdown: float,
        stability: float,
        slippage_adj: float,
        support_count: int,
        drift: float,
        diversity: float = 1.0,
    ) -> Tuple[bool, str]:
        t = self.thresholds
        if score < t.min_score:
            decision, reason = False, "PROMOTION_FAIL_SCORE"
        elif drawdown > t.max_drawdown:
            decision, reason = False, "PROMOTION_FAIL_DRAWDOWN"
        elif stability < t.min_stability:
            decision, reason = False, "PROMOTION_FAIL_STABILITY"
        elif slippage_adj < t.min_slippage_adj:
            decision, reason = False, "PROMOTION_FAIL_SLIPPAGE_ADJ"
        elif support_count < t.min_support:
            decision, reason = False, "PROMOTION_FAIL_SUPPORT"
        elif drift > t.max_drift:
            decision, reason = False, "PROMOTION_FAIL_DRIFT"
        elif diversity < t.min_diversity:
            decision, reason = False, "PROMOTION_FAIL_DIVERSITY"
        else:
            decision, reason = True, "PROMOTION_PASS"

        self.lib.write_promotion_decision(
            run_id=self.run_id,
            candidate_id=candidate_id,
            decision="promoted" if decision else "kept_prior",
            reason_code=reason,
            score=score,
            drawdown=drawdown,
            stability=stability,
            slippage_adj=slippage_adj,
            support_count=support_count,
            drift=drift,
        )
        return decision, reason
