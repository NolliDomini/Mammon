from __future__ import annotations

import os
import sys
import threading

from Hippocampus.Archivist.librarian import Librarian
from Hippocampus.tests_v2.fixtures.factories import frame_stub, temp_db_path
from Medulla.treasury_gland import TreasuryGland


project_root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if project_root not in sys.path:
    sys.path.append(project_root)

import Brain_Stem.connection as connection_mod
from Brain_Stem.connection import Trigger


def _mk_orch(trading_enabled=True):
    class Orch:
        config = {"trading_enabled_provider": staticmethod(lambda: trading_enabled)}

    return Orch()


def _mk_trigger(tmp_db, config=None):
    t = Trigger.__new__(Trigger)
    t.config = config or {}
    t.api_key = "k"
    t.api_secret = "s"
    t.client = None
    t.execution_mode = "DRY_RUN"
    t.execution_adapter = "mock"
    t._adapter_lock = threading.Lock()
    t.rng = None
    t.risk_score = 0.0
    t.last_trigger_score = 0.0
    t.prev_price = None
    t.position = None
    t.last_exit_reason = None
    t.pending_entry = None
    t.mean_dev_monitor_active = False
    t.last_execution_event = {}
    t.treasury = TreasuryGland(mode="DRY_RUN", librarian=Librarian(db_path=tmp_db))
    return t


def test_brain_stem_does_not_approve_when_command_not_fire_eligible():
    dbp = temp_db_path("v2_exec_policy_block")
    trigger = _mk_trigger(dbp)
    frame = frame_stub(price=100.0)
    frame.command.ready_to_fire = False
    frame.command.approved = 0
    trigger.load_and_hunt("ACTION", frame, orchestrator=_mk_orch(True), walk_engine=None)
    assert trigger.pending_entry is None
    rows = trigger.treasury.librarian.read_only("SELECT COUNT(*) AS c FROM money_orders")
    assert int(rows[0]["c"]) == 0


def test_action_rejects_invalid_payload_with_terminal_treasury_state():
    dbp = temp_db_path("v2_exec_invalid_payload")
    trigger = _mk_trigger(dbp)
    frame = frame_stub(price=100.0)
    frame.market.symbol = ""
    frame.command.ready_to_fire = True
    frame.command.approved = 1
    frame.command.sizing_mult = 0.0
    trigger.load_and_hunt("ACTION", frame, orchestrator=_mk_orch(True), walk_engine=None)
    rows = trigger.treasury.librarian.read_only(
        "SELECT status, reason FROM money_orders ORDER BY ts DESC LIMIT 1"
    )
    assert rows and rows[0]["status"] == "REJECTED"
    assert "REJECT_INVALID_PAYLOAD" in (rows[0]["reason"] or "")


def test_action_trading_gate_disabled_preempts_arm():
    dbp = temp_db_path("v2_exec_gate_lock")
    trigger = _mk_trigger(dbp, {"brain_stem_mean_dev_cancel_sigma": 99.0})
    trigger._run_risk_gate = lambda frame, prior: 0.9
    trigger._run_valuation_gate = lambda frame, prior, walk_seed=None: {
        "mean": frame.structure.price + 1.0,
        "sigma": 1.0,
        "upper": frame.structure.price + 2.0,
        "lower": frame.structure.price - 2.0,
    }
    frame = frame_stub(price=100.0)
    frame.command.ready_to_fire = True
    frame.command.approved = 1
    trigger.load_and_hunt("ACTION", frame, orchestrator=_mk_orch(False), walk_engine=None)
    assert trigger.pending_entry is None
    rows = trigger.treasury.librarian.read_only("SELECT COUNT(*) AS c FROM money_orders")
    assert int(rows[0]["c"]) == 0


def test_mint_adapter_failure_is_rejected_and_not_marked_filled():
    dbp = temp_db_path("v2_exec_adapter_fail")
    trigger = _mk_trigger(dbp, {"brain_stem_mean_dev_cancel_sigma": 99.0})
    trigger._run_risk_gate = lambda frame, prior: 0.9
    trigger._run_valuation_gate = lambda frame, prior, walk_seed=None: {
        "mean": frame.structure.price + 1.0,
        "sigma": 1.0,
        "upper": frame.structure.price + 2.0,
        "lower": frame.structure.price - 2.0,
    }
    trigger._fire_physical = lambda *args, **kwargs: {"status": "error", "msg": "broker down"}

    frame = frame_stub(price=100.0)
    frame.command.ready_to_fire = True
    frame.command.approved = 1
    trigger.load_and_hunt("ACTION", frame, orchestrator=_mk_orch(True), walk_engine=None)
    trigger.load_and_hunt("MINT", frame, orchestrator=_mk_orch(True), walk_engine=None)

    rows = trigger.treasury.librarian.read_only(
        "SELECT status, reason FROM money_orders ORDER BY ts DESC LIMIT 1"
    )
    assert rows and rows[0]["status"] == "REJECTED"
    assert "REJECT_ADAPTER_FAILURE" in (rows[0]["reason"] or "")
    assert trigger.position is None


def test_adapter_routing_and_fallback_contract(monkeypatch):
    class FakeTradingClient:
        def __init__(self, api_key, api_secret, paper=True):
            self.paper = paper

    monkeypatch.setattr(connection_mod, "TradingClient", FakeTradingClient)
    t = Trigger(api_key="k", api_secret="s", paper=True, config={"execution_mode": "DRY_RUN"})
    assert t.execution_adapter == "mock"
    t.set_execution_mode("BACKTEST")
    assert t.execution_adapter == "mock"
    t.set_execution_mode("PAPER")
    assert t.execution_adapter == "alpaca"
    t.set_execution_mode("LIVE")
    assert t.execution_adapter == "alpaca"

    class BrokenTradingClient:
        def __init__(self, api_key, api_secret, paper=True):
            raise RuntimeError("bind fail")

    monkeypatch.setattr(connection_mod, "TradingClient", BrokenTradingClient)
    t.set_execution_mode("LIVE")
    assert t.execution_adapter == "mock"
    assert t.client is None


def test_runtime_mode_rebind_no_adapter_drift_while_active():
    dbp = temp_db_path("v2_exec_mode_rebind")
    trigger = _mk_trigger(dbp)
    trigger.pending_entry = {"intent_id": "x", "symbol": "BTC/USD", "qty": 1.0, "armed_price": 100.0}
    trigger.set_execution_mode("BACKTEST")
    assert trigger.execution_mode == "BACKTEST"
    assert trigger.execution_adapter == "mock"
    assert trigger.treasury is not None
    assert trigger.treasury.mode == "BACKTEST"
    assert trigger.pending_entry is not None

