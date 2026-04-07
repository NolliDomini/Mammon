import sqlite3

from Hippocampus.Archivist.optimizer_librarian import OptimizerLibrarian
from Hippocampus.tests_v2.fixtures.factories import temp_db_path
from Hospital.Optimizer_loop.optimizer_v2 import OptimizerV2Engine, V2Budget


def test_optimizer_v2_promotion_fails_when_diversity_floor_not_met():
    db_path = temp_db_path("v2_opt_diversity_guard")
    lib = OptimizerLibrarian(db_path=db_path)
    lib.setup_schema()

    engine = OptimizerV2Engine(
        run_id="run-v2-diversity",
        librarian=lib,
        seed=7,
        budget=V2Budget(edge_lhs_n=24, stage_c_n=16, stage_f_n=10, diversity_floor=5.0),
    )
    summary = engine.run_pipeline(
        regime_id="R_DIV",
        price=100.0,
        atr=1.2,
        stop_level=98.6,
        allow_bayesian=True,
    )
    assert summary["status"] == "ok"
    assert summary["promoted"] is False
    assert summary["promotion_reason"] == "PROMOTION_FAIL_DIVERSITY"

    with sqlite3.connect(db_path) as con:
        reason = con.execute(
            "SELECT reason_code FROM opt_promotion_decisions WHERE run_id=? ORDER BY id DESC LIMIT 1",
            ("run-v2-diversity",),
        ).fetchone()[0]
    assert reason == "PROMOTION_FAIL_DIVERSITY"
