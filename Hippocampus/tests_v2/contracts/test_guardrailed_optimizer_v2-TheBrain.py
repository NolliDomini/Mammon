from Hippocampus.Archivist.librarian import MultiTransportLibrarian as OptimizerLibrarian
from Hospital.Optimizer_loop.guardrailed_optimizer import (
    GuardrailedOptimizer,
    PromotionThresholds,
    ScoreVector,
)
from Hippocampus.tests_v2.fixtures.factories import temp_db_path


def test_guardrail_tables_created_and_stage_audit_written():
    db_path = temp_db_path("v2_opt_guard")
    lib = OptimizerLibrarian(db_path=db_path)
    lib.setup_schema()
    opt = GuardrailedOptimizer(run_id="run-v2-a", librarian=lib)
    opt.log_stage_start("edge_lhs_scan", regime_id="R1")
    opt.log_stage_complete("edge_lhs_scan", regime_id="R1", metrics={"n": 42})
    opt.log_stage_drop("bayesian_major_search", reason_code="BAYESIAN_SKIP_CADENCE", regime_id="R1")

    rows = lib.write_batch  # keep linter quiet in minimal style
    con_rows = []
    import sqlite3

    with sqlite3.connect(db_path) as con:
        con_rows = con.execute("SELECT stage_name, status FROM opt_stage_runs ORDER BY id").fetchall()
    assert len(con_rows) == 3
    assert con_rows[0][0] == "edge_lhs_scan"


def test_component_scoring_and_promotion_gate_reason_codes():
    db_path = temp_db_path("v2_opt_score")
    lib = OptimizerLibrarian(db_path=db_path)
    lib.setup_schema()
    opt = GuardrailedOptimizer(
        run_id="run-v2-b",
        librarian=lib,
        thresholds=PromotionThresholds(min_score=0.60, min_support=10),
    )

    opt.register_candidate("cand-1", "stage_f", {"a": 1}, regime_id="R2", support_count=5)
    _, robust = opt.compute_scores(
        "cand-1",
        ScoreVector(
            expectancy=0.8,
            survival=0.7,
            stability=0.6,
            drawdown=0.1,
            uncertainty=0.2,
            slippage_cost=0.1,
            score_std=0.05,
        ),
    )
    decision, reason = opt.promotion_decision(
        "cand-1",
        score=max(0.8, robust),
        drawdown=0.1,
        stability=0.6,
        slippage_adj=0.7,
        support_count=5,
        drift=0.1,
    )
    assert decision is False
    assert reason == "PROMOTION_FAIL_SUPPORT"

    decision2, reason2 = opt.promotion_decision(
        "cand-1",
        score=0.9,
        drawdown=0.05,
        stability=0.9,
        slippage_adj=0.9,
        support_count=20,
        drift=0.05,
    )
    assert decision2 is True
    assert reason2 == "PROMOTION_PASS"
