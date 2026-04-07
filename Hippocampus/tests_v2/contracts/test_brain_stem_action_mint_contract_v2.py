from __future__ import annotations

import os
import sys

from Hippocampus.Archivist.librarian import Librarian
from Medulla.treasury_gland import TreasuryGland
from Hippocampus.tests_v2.fixtures.factories import frame_stub, temp_db_path


project_root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if project_root not in sys.path:
    sys.path.append(project_root)

from Brain_Stem.connection import Trigger


def _mk_trigger(tmp_db, config=None):
    t = Trigger.__new__(Trigger)
    t.config = config or {}
    t.client = None
    t.execution_mode = "DRY_RUN"
    t.execution_adapter = "mock"
    t.rng = None
    t.risk_score = 0.0
    t.last_trigger_score = 0.0
    t.prev_price = None
    t.position = None
    t.last_exit_reason = None
    t.pending_entry = None
    t.mean_dev_monitor_active = False
    t.treasury = TreasuryGland(mode="DRY_RUN", librarian=Librarian(db_path=tmp_db))
    return t


def _mk_orch(trading_enabled=True):
    class Orch:
        config = {"trading_enabled_provider": staticmethod(lambda: trading_enabled)}

    return Orch()


def test_action_arm_then_mint_fire_persists_terminal_state():
    dbp = temp_db_path("v2_contract_fire")
    trigger = _mk_trigger(dbp, {"brain_stem_mean_dev_cancel_sigma": 99.0})
    trigger._run_risk_gate = lambda frame, prior: 0.9
    trigger._run_valuation_gate = lambda frame, prior, walk_seed=None: {
        "mean": frame.structure.price + 1.0,
        "sigma": 1.0,
        "upper": frame.structure.price + 2.0,
        "lower": frame.structure.price - 2.0,
    }
    fired = []
    trigger._fire_physical = lambda symbol, side, qty, price: fired.append((symbol, side, qty, price))

    frame = frame_stub(price=100.0)
    trigger.load_and_hunt("ACTION", frame, orchestrator=_mk_orch(True), walk_engine=None)
    assert trigger.pending_entry is not None
    trigger.load_and_hunt("MINT", frame, orchestrator=_mk_orch(True), walk_engine=None)

    rows = trigger.treasury.librarian.read_only(
        "SELECT status FROM money_orders ORDER BY ts DESC LIMIT 1"
    )
    assert rows and rows[0]["status"] == "FILLED"
    assert fired == [("BTC/USD", "BUY", 1.0, 100.0)]


def test_action_arm_then_mint_cancel_on_mode_gate():
    dbp = temp_db_path("v2_contract_cancel")
    trigger = _mk_trigger(dbp, {"brain_stem_mean_dev_cancel_sigma": 99.0})
    trigger._run_risk_gate = lambda frame, prior: 0.9
    trigger._run_valuation_gate = lambda frame, prior, walk_seed=None: {
        "mean": frame.structure.price + 1.0,
        "sigma": 1.0,
        "upper": frame.structure.price + 2.0,
        "lower": frame.structure.price - 2.0,
    }
    trigger._fire_physical = lambda *args, **kwargs: None
    frame = frame_stub(price=100.0)
    trigger.load_and_hunt("ACTION", frame, orchestrator=_mk_orch(True), walk_engine=None)
    trigger.load_and_hunt("MINT", frame, orchestrator=_mk_orch(False), walk_engine=None)

    rows = trigger.treasury.librarian.read_only(
        "SELECT status, reason FROM money_orders ORDER BY ts DESC LIMIT 1"
    )
    assert rows and rows[0]["status"] == "CANCELED"
    assert "MODE_GATE_CANCEL" in (rows[0]["reason"] or "")
