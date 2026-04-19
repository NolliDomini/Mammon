from __future__ import annotations

from pathlib import Path

from Cerebellum.Soul.brain_frame import BrainFrame
from Hippocampus.amygdala import Amygdala
from Hippocampus.Archivist.librarian import Librarian
from Hippocampus.Archivist.synapse_scribe import SynapseScribe
from Hippocampus.tests_v2.fixtures.factories import synthetic_ohlcv, temp_db_path


def _frame() -> BrainFrame:
    f = BrainFrame()
    df = synthetic_ohlcv(periods=20)
    f.market.ohlcv = df
    f.market.ts = df.index[-1]
    f.market.symbol = "BTC/USD"
    f.market.execution_mode = "DRY_RUN"
    f.market.pulse_type = "MINT"
    f.structure.price = float(df["close"].iloc[-1])
    f.structure.active_hi = float(df["high"].iloc[-5:].max())
    f.structure.active_lo = float(df["low"].iloc[-5:].min())
    f.structure.gear = 5
    f.structure.tier1_signal = 1
    f.risk.monte_score = 0.81
    f.risk.tier_score = 0.79
    f.risk.regime_id = "R1"
    f.environment.confidence = 0.77
    f.environment.atr = 1.2
    f.environment.atr_avg = 1.1
    f.environment.adx = 28.0
    f.environment.volume_score = 0.88
    f.command.reason = "APPROVED"
    f.command.approved = 1
    f.command.final_confidence = 0.78
    f.command.sizing_mult = 1.0
    f.command.ready_to_fire = True
    return f


def _mk_amygdala(tmp_db: Path) -> Amygdala:
    scribe = SynapseScribe(db_path=tmp_db)
    return Amygdala(scribe=scribe)


def _rows(tmp_db: Path, sql: str):
    if not Path(tmp_db).exists():
        return [{"c": 0}]
    lib = Librarian(db_path=tmp_db)
    return lib.read_only(sql)


def test_non_mint_pulses_do_not_persist_synapse_ticket():
    dbp = temp_db_path("v2_amygdala_non_mint")
    a = _mk_amygdala(dbp)
    f = _frame()
    a.mint_synapse_ticket("SEED", f)
    a.mint_synapse_ticket("ACTION", f)
    rows = _rows(dbp, "SELECT COUNT(*) AS c FROM synapse_mint")
    assert int(rows[0]["c"]) == 0


def test_decision_quality_mode_persists_seed_action_and_mint():
    dbp = temp_db_path("v2_amygdala_decision_quality")
    a = Amygdala(
        config={
            "synapse_db_path_primary": str(dbp),
            "synapse_persist_pulse_types": ["SEED", "ACTION", "MINT"],
        }
    )
    f = _frame()
    a.mint_synapse_ticket("SEED", f)
    a.mint_synapse_ticket("ACTION", f)
    f.market.ts = f.market.ts + (f.market.ohlcv.index[1] - f.market.ohlcv.index[0])
    a.mint_synapse_ticket("MINT", f)
    rows = _rows(dbp, "SELECT pulse_type, COUNT(*) AS c FROM synapse_mint GROUP BY pulse_type")
    counts = {str(r["pulse_type"]).upper(): int(r["c"]) for r in rows}
    assert counts.get("SEED", 0) == 1
    assert counts.get("ACTION", 0) == 1
    assert counts.get("MINT", 0) == 1


def test_mint_writes_required_snapshot_schema_fields():
    dbp = temp_db_path("v2_amygdala_required_schema")
    a = _mk_amygdala(dbp)
    f = _frame()
    a.mint_synapse_ticket("MINT", f)
    rows = _rows(
        dbp,
        "SELECT ts, symbol, pulse_type, monte_score, tier_score, atr, decision, approved, machine_code FROM synapse_mint LIMIT 1",
    )
    assert rows
    row = rows[0]
    assert row["symbol"] == "BTC/USD"
    assert row["pulse_type"] == "MINT"
    assert row["machine_code"] is not None


def test_machine_code_is_present_and_deterministic_for_identical_input():
    dbp = temp_db_path("v2_amygdala_machine_code_deterministic")
    a = _mk_amygdala(dbp)
    f = _frame()
    a.mint_synapse_ticket("MINT", f)
    first = a.get_state()["last_machine_code"]
    a.mint_synapse_ticket("MINT", f)
    second = a.get_state()["last_machine_code"]
    assert first == second
    rows = _rows(dbp, "SELECT COUNT(*) AS c FROM synapse_mint")
    # PK idempotency: repeated MINT for same ts/symbol/pulse replaces row.
    assert int(rows[0]["c"]) == 1


def test_machine_code_changes_for_distinct_cardinality_inputs():
    dbp = temp_db_path("v2_amygdala_machine_code_unique")
    a = _mk_amygdala(dbp)
    f1 = _frame()
    f2 = _frame()
    f2.market.ts = f2.market.ts + (f2.market.ohlcv.index[1] - f2.market.ohlcv.index[0])
    a.mint_synapse_ticket("MINT", f1)
    code1 = a.get_state()["last_machine_code"]
    a.mint_synapse_ticket("MINT", f2)
    code2 = a.get_state()["last_machine_code"]
    assert code1 != code2


def test_schema_mismatch_rejects_without_crashing():
    dbp = temp_db_path("v2_amygdala_schema_reject")
    a = _mk_amygdala(dbp)
    f = _frame()
    f.market.symbol = ""
    a.mint_synapse_ticket("MINT", f)
    st = a.get_state()
    assert st["last_write_status"] == "REJECTED"
    assert st["last_error_code"] == "INVALID_SYMBOL"
    rows = _rows(dbp, "SELECT COUNT(*) AS c FROM synapse_mint")
    assert int(rows[0]["c"]) == 0


def test_write_failures_are_reported_and_non_fatal():
    dbp = temp_db_path("v2_amygdala_write_failure")
    a = _mk_amygdala(dbp)
    a.scribe = type("BrokenScribe", (), {"mint": lambda self, ticket: (_ for _ in ()).throw(RuntimeError("db down"))})()
    f = _frame()
    a.mint_synapse_ticket("MINT", f)
    st = a.get_state()
    assert st["last_write_status"] == "ERROR"
    assert st["last_error_code"] == "WRITE_FAILURE"


def test_machine_code_index_exists_and_is_used_for_lookup():
    dbp = temp_db_path("v2_amygdala_machine_code_index")
    a = _mk_amygdala(dbp)
    f = _frame()
    a.mint_synapse_ticket("MINT", f)
    idx = _rows(dbp, "PRAGMA index_list('synapse_mint')")
    names = {r["name"] for r in idx}
    assert "idx_synapse_mint_machine_code" in names

    code = a.get_state()["last_machine_code"]
    qp = _rows(dbp, f"EXPLAIN QUERY PLAN SELECT * FROM synapse_mint WHERE machine_code = '{code}'")
    plan = " ".join(str(r.get("detail", "")) for r in qp).upper()
    assert "IDX_SYNAPSE_MINT_MACHINE_CODE" in plan or "MACHINE_CODE" in plan


def test_backtest_mode_routes_synapse_writes_to_dedicated_db():
    primary = temp_db_path("v2_amygdala_primary")
    backtest = temp_db_path("v2_amygdala_backtest")
    a = Amygdala(
        config={
            "synapse_db_path_primary": str(primary),
            "synapse_db_path_backtest": str(backtest),
        }
    )
    f = _frame()
    f.market.execution_mode = "BACKTEST"
    a.mint_synapse_ticket("MINT", f)

    primary_rows = _rows(primary, "SELECT COUNT(*) AS c FROM synapse_mint")
    backtest_rows = _rows(backtest, "SELECT COUNT(*) AS c FROM synapse_mint")
    assert int(primary_rows[0]["c"]) == 0
    assert int(backtest_rows[0]["c"]) == 1
    assert str(backtest) == a.get_state()["last_target_db"]


def test_non_backtest_mode_routes_synapse_writes_to_primary_db():
    primary = temp_db_path("v2_amygdala_primary_runtime")
    backtest = temp_db_path("v2_amygdala_backtest_runtime")
    a = Amygdala(
        config={
            "synapse_db_path_primary": str(primary),
            "synapse_db_path_backtest": str(backtest),
        }
    )
    f = _frame()
    f.market.execution_mode = "LIVE"
    a.mint_synapse_ticket("MINT", f)

    primary_rows = _rows(primary, "SELECT COUNT(*) AS c FROM synapse_mint")
    backtest_rows = _rows(backtest, "SELECT COUNT(*) AS c FROM synapse_mint")
    assert int(primary_rows[0]["c"]) == 1
    assert int(backtest_rows[0]["c"]) == 0
    assert str(primary) == a.get_state()["last_target_db"]
