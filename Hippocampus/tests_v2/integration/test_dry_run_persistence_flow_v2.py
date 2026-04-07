from Hippocampus.Archivist.librarian import Librarian
from Medulla.treasury_gland import TreasuryGland
from Hippocampus.tests_v2.fixtures.factories import frame_stub, temp_db_path
from Brain_Stem.connection import Trigger


def _mk_orch(trading_enabled=True):
    class Orch:
        config = {"trading_enabled_provider": staticmethod(lambda: trading_enabled)}

    return Orch()


def _mk_trigger_with_treasury(db_path, cancel_sigma):
    t = Trigger.__new__(Trigger)
    t.config = {"brain_stem_mean_dev_cancel_sigma": cancel_sigma}
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
    t.treasury = TreasuryGland(mode="DRY_RUN", librarian=Librarian(db_path=db_path))
    t._run_risk_gate = lambda frame, prior: 0.9
    t._run_valuation_gate = lambda frame, prior, walk_seed=None: {
        "mean": frame.structure.price + 1.0,
        "sigma": 1.0,
        "upper": frame.structure.price + 2.0,
        "lower": frame.structure.price - 2.0,
    }
    t._fire_physical = lambda *args, **kwargs: {"status": "fired"}
    return t


def test_action_to_mint_fire_persists_order_fill_position():
    db_path = temp_db_path("v2_integ_fire")
    trigger = _mk_trigger_with_treasury(db_path, cancel_sigma=99.0)
    frame = frame_stub(price=100.0)

    trigger.load_and_hunt("ACTION", frame, orchestrator=_mk_orch(True), walk_engine=None)
    trigger.load_and_hunt("MINT", frame, orchestrator=_mk_orch(True), walk_engine=None)

    lib = trigger.treasury.librarian
    order = lib.read_only("SELECT status FROM money_orders ORDER BY ts DESC LIMIT 1")[0]
    fill = lib.read_only("SELECT count(*) AS c FROM money_fills")[0]
    pos = lib.read_only("SELECT count(*) AS c FROM money_positions")[0]
    assert order["status"] == "FILLED"
    assert int(fill["c"]) == 1
    assert int(pos["c"]) == 1


def test_action_to_mint_cancel_persists_without_fill():
    db_path = temp_db_path("v2_integ_cancel")
    trigger = _mk_trigger_with_treasury(db_path, cancel_sigma=-99.0)
    frame = frame_stub(price=100.0)

    trigger.load_and_hunt("ACTION", frame, orchestrator=_mk_orch(True), walk_engine=None)
    trigger.load_and_hunt("MINT", frame, orchestrator=_mk_orch(True), walk_engine=None)

    lib = trigger.treasury.librarian
    order = lib.read_only("SELECT status FROM money_orders ORDER BY ts DESC LIMIT 1")[0]
    fill = lib.read_only("SELECT count(*) AS c FROM money_fills")[0]
    assert order["status"] == "CANCELED"
    assert int(fill["c"]) == 0
