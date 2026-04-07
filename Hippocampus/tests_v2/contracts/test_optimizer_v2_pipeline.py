import sqlite3

from Hippocampus.Archivist.optimizer_librarian import OptimizerLibrarian
from Hippocampus.tests_v2.fixtures.factories import temp_db_path
from Hospital.Optimizer_loop.optimizer_v2 import OptimizerV2Engine, V2Budget


def test_optimizer_v2_pipeline_persists_stage_and_guardrail_artifacts():
    db_path = temp_db_path("v2_opt_pipeline")
    lib = OptimizerLibrarian(db_path=db_path)
    lib.setup_schema()

    engine = OptimizerV2Engine(
        run_id="run-v2-pipeline",
        librarian=lib,
        seed=1337,
        budget=V2Budget(edge_lhs_n=24, stage_c_n=28, stage_f_n=12),
    )
    summary = engine.run_pipeline(
        regime_id="R_PIPE",
        price=100.0,
        atr=1.5,
        stop_level=98.0,
        allow_bayesian=True,
    )

    assert summary["status"] == "ok"
    assert summary["winner_candidate_id"]

    with sqlite3.connect(db_path) as con:
        stage_runs = con.execute("SELECT COUNT(*) FROM opt_stage_runs").fetchone()[0]
        scores = con.execute("SELECT COUNT(*) FROM opt_scores_components").fetchone()[0]
        diversity = con.execute("SELECT COUNT(*) FROM opt_diversity_metrics").fetchone()[0]
        coverage = con.execute("SELECT COUNT(*) FROM opt_regime_coverage").fetchone()[0]
        promo = con.execute("SELECT COUNT(*) FROM opt_promotion_decisions").fetchone()[0]

    assert stage_runs > 0
    assert scores > 0
    assert diversity > 0
    assert coverage > 0
    assert promo > 0
