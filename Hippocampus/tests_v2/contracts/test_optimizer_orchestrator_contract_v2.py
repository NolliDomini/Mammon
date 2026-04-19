from __future__ import annotations

from types import SimpleNamespace

from Cerebellum.Soul.brain_frame import BrainFrame
from Hospital.Optimizer_loop.volume_furnace_orchestrator import VolumeFurnaceOrchestrator


def _furnace(
    *,
    mode: str = "DRY_RUN",
    external_cadence: bool = False,
):
    f = VolumeFurnaceOrchestrator.__new__(VolumeFurnaceOrchestrator)
    f.run_id = "forge-test"
    f.execution_mode = mode
    f.simulation_mode = mode == "BACKTEST"
    f.external_cadence = external_cadence
    f.shutdown_requested = False
    f.pulse_count = 0
    f.mint_count = 0
    f.activation_count = 0
    f.last_decision = "INIT"
    f.last_summary = {}
    f.last_error = None
    f.telemetry = []
    f.telemetry_limit = 200
    calls = []
    f.engine = SimpleNamespace(run_pipeline=lambda **kwargs: calls.append(kwargs) or {"promoted": False, "reason": "NO_PROMOTION"})
    return f, calls


def _frame(*, mode: str = "DRY_RUN", regime: str = "R1", price: float = 100.0, atr: float = 1.0, stop: float = 99.0):
    fr = BrainFrame()
    fr.market.execution_mode = mode
    fr.risk.regime_id = regime
    fr.structure.price = price
    fr.environment.atr = atr
    fr.structure.active_lo = stop
    fr.risk.mutations = [0.1, 0.2]
    return fr


def test_optimizer_runs_only_when_cadence_and_mode_gates_permit():
    f, calls = _furnace(mode="DRY_RUN", external_cadence=False)
    fr = _frame(mode="DRY_RUN")

    for _ in range(9):
        f.handle_frame(pulse_type="MINT", frame=fr, walk_seed=SimpleNamespace(regime_id="R1", mutations=[0.1], support_floor_ok=True))

    assert len(calls) == 3
    assert f.last_decision in {"EXECUTED", "CADENCE_GATE"}

    f_bad, calls_bad = _furnace(mode="BROKEN", external_cadence=False)
    bad_frame = _frame(mode="BROKEN")
    f_bad.handle_frame(pulse_type="MINT", frame=bad_frame, walk_seed=SimpleNamespace(regime_id="R1", mutations=[0.1], support_floor_ok=True))
    assert len(calls_bad) == 0
    assert f_bad.last_decision == "MODE_GATE"


def test_optimizer_consumes_frame_truth_contract_without_schema_branching():
    f, calls = _furnace(mode="DRY_RUN", external_cadence=True)
    fr = _frame(mode="PAPER", regime="R_FRAME", price=123.45, atr=2.5, stop=118.0)
    fr.risk.mutations = [0.11, 0.22, 0.33]

    f.handle_frame(pulse_type="MINT", frame=fr, walk_seed=None)

    assert len(calls) == 1
    kwargs = calls[0]
    assert kwargs["regime_id"] == "R_FRAME"
    assert kwargs["price"] == 123.45
    assert kwargs["atr"] == 2.5
    assert kwargs["stop_level"] == 118.0
    assert kwargs["mutations"] == [0.11, 0.22, 0.33]
    assert f.execution_mode == "PAPER"


def test_optimizer_live_backtest_cadence_behavior_is_deterministic():
    live, live_calls = _furnace(mode="LIVE", external_cadence=False)
    fr_live = _frame(mode="LIVE")
    for _ in range(9):
        live.handle_frame(pulse_type="MINT", frame=fr_live, walk_seed=SimpleNamespace(regime_id="R1", mutations=[0.1], support_floor_ok=True))
    assert len(live_calls) == 3

    back, back_calls = _furnace(mode="BACKTEST", external_cadence=True)
    fr_back = _frame(mode="BACKTEST")
    for _ in range(12):
        back.handle_frame(pulse_type="MINT", frame=fr_back, walk_seed=SimpleNamespace(regime_id="R2", mutations=[0.1], support_floor_ok=True))
    assert len(back_calls) == 3


def test_optimizer_skip_reasons_and_error_isolation_are_explicit():
    f, calls = _furnace(mode="DRY_RUN", external_cadence=True)
    fr = _frame(mode="DRY_RUN")

    f.shutdown_requested = True
    f.handle_frame(pulse_type="MINT", frame=fr, walk_seed=SimpleNamespace(regime_id="R1", mutations=[0.1], support_floor_ok=True))
    assert f.last_decision == "SHUTDOWN"
    assert len(calls) == 0

    f.shutdown_requested = False
    fr_missing = _frame(mode="DRY_RUN", atr=0.0, stop=0.0)
    f.handle_frame(pulse_type="MINT", frame=fr_missing, walk_seed=SimpleNamespace(regime_id="R1", mutations=[0.1], support_floor_ok=True))
    assert f.last_decision == "EXECUTED"
    assert calls[-1]["atr"] > 0.0
    assert calls[-1]["stop_level"] > 0.0

    fr_support = _frame(mode="DRY_RUN")
    f.handle_frame(pulse_type="MINT", frame=fr_support, walk_seed=SimpleNamespace(regime_id="R1", mutations=[0.1], support_floor_ok=False))
    assert f.last_decision == "SUPPORT_FLOOR"

    f_err, err_calls = _furnace(mode="DRY_RUN", external_cadence=True)
    f_err.engine = SimpleNamespace(run_pipeline=lambda **kwargs: (_ for _ in ()).throw(RuntimeError("boom")))
    f_err.handle_frame(pulse_type="MINT", frame=_frame(mode="DRY_RUN"), walk_seed=SimpleNamespace(regime_id="R1", mutations=[0.1], support_floor_ok=True))
    assert len(err_calls) == 0
    assert f_err.last_decision == "PIPELINE_ERROR"
    assert f_err.last_error == "boom"


def test_external_cadence_path_is_contract_consistent_with_handle_pulse():
    f_frame, calls_frame = _furnace(mode="BACKTEST", external_cadence=True)
    f_pulse, calls_pulse = _furnace(mode="BACKTEST", external_cadence=True)
    fr = _frame(mode="BACKTEST", regime="R_SYNC", price=101.0, atr=1.1, stop=99.4)
    seed = SimpleNamespace(regime_id="R_SYNC", mutations=[0.3], support_floor_ok=True)

    for _ in range(12):
        f_frame.handle_frame(pulse_type="MINT", frame=fr, walk_seed=seed)
        f_pulse.handle_pulse(
            pulse_type="MINT",
            regime_id="R_SYNC",
            price=101.0,
            atr=1.1,
            stop_level=99.4,
            walk_seed=seed,
        )

    assert len(calls_frame) == len(calls_pulse) == 3


def test_promotion_decisions_are_telemetried_and_auditable():
    f, calls = _furnace(mode="DRY_RUN", external_cadence=True)
    f.engine = SimpleNamespace(
        run_pipeline=lambda **kwargs: calls.append(kwargs) or {"promoted": True, "reason": "PROMOTED", "winner_id": "cand-1"}
    )
    fr = _frame(mode="DRY_RUN")
    f.handle_frame(pulse_type="MINT", frame=fr, walk_seed=SimpleNamespace(regime_id="R1", mutations=[0.2], support_floor_ok=True))

    state = f.get_state()
    assert len(calls) == 1
    assert state["last_decision"] == "EXECUTED"
    assert state["last_summary"]["promoted"] is True
    tail = state["telemetry_tail"][-1]
    assert tail["promotion_decision"] == "PROMOTED"
