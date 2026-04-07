from types import SimpleNamespace

import pandas as pd

from Cerebellum.Soul.brain_frame import BrainFrame
from Cerebellum.Soul.orchestrator import Orchestrator
from Right_Hemisphere.Snapping_Turtle.engine import SnappingTurtle
from Hippocampus.tests_v2.fixtures.factories import synthetic_ohlcv


def _frame(df: pd.DataFrame) -> BrainFrame:
    f = BrainFrame()
    f.market.ohlcv = df
    f.market.ts = df.index[-1]
    f.market.symbol = "BTC/USD"
    f.market.pulse_type = "ACTION"
    f.market.execution_mode = "DRY_RUN"
    return f


def test_right_hemisphere_mutates_only_structure_slot():
    df = synthetic_ohlcv(periods=10)
    frame = _frame(df)
    t = SnappingTurtle(config={"active_gear": 5})

    before_market = (frame.market.ts, frame.market.symbol, frame.market.pulse_type, frame.market.execution_mode, id(frame.market.ohlcv))
    before_risk = frame.risk.__dict__.copy()
    before_env = frame.environment.__dict__.copy()
    before_cmd = frame.command.__dict__.copy()

    t.on_data_received("ACTION", frame=frame)

    after_market = (frame.market.ts, frame.market.symbol, frame.market.pulse_type, frame.market.execution_mode, id(frame.market.ohlcv))
    assert before_market == after_market
    assert before_risk == frame.risk.__dict__
    assert before_env == frame.environment.__dict__
    assert before_cmd == frame.command.__dict__
    assert frame.structure.gear == 5


def test_right_hemisphere_is_deterministic_for_same_input_across_pulses():
    df = synthetic_ohlcv(periods=10)
    t = SnappingTurtle(config={"active_gear": 5})
    outputs = []
    for pulse in ("SEED", "ACTION", "MINT"):
        frame = _frame(df.copy())
        frame.market.pulse_type = pulse
        _, strikes = t.on_data_received(pulse, frame=frame)
        outputs.append(
            (
                frame.structure.active_hi,
                frame.structure.active_lo,
                frame.structure.gear,
                frame.structure.tier1_signal,
                frame.structure.price,
                len(strikes),
            )
        )
    assert outputs[0] == outputs[1] == outputs[2]


def test_insufficient_history_resets_safe_structure_state():
    df = synthetic_ohlcv(periods=3)
    frame = _frame(df)
    t = SnappingTurtle(config={"active_gear": 5})

    data, strikes = t.on_data_received("ACTION", frame=frame)
    assert data is None
    assert strikes == []
    assert frame.structure.active_hi == 0.0
    assert frame.structure.active_lo == 0.0
    assert frame.structure.tier1_signal == 0
    assert frame.structure.gear == 5
    assert t.get_state()["last_paint_event"]["status"] == "insufficient_history"


def test_malformed_input_is_fail_safe_and_deterministic():
    df_missing = pd.DataFrame([{"open": 1.0, "close": 1.0, "symbol": "BTC/USD"}], index=pd.to_datetime(["2026-01-01T00:00:00Z"]))
    frame = _frame(df_missing)
    t = SnappingTurtle(config={"active_gear": 5})
    data, strikes = t.on_data_received("ACTION", frame=frame)
    assert data is None and strikes == []
    assert t.get_state()["last_paint_event"]["status"] == "schema_mismatch"

    df_bad = pd.DataFrame(
        [{"open": 1.0, "high": "x", "low": 0.5, "close": 1.0, "volume": 1.0, "symbol": "BTC/USD"}],
        index=pd.to_datetime(["2026-01-01T00:00:00Z"]),
    )
    frame2 = _frame(df_bad)
    data2, strikes2 = t.on_data_received("ACTION", frame=frame2)
    assert data2 is None and strikes2 == []
    assert t.get_state()["last_paint_event"]["status"] == "non_numeric_ohlc"


def test_legacy_dataframe_only_handler_is_not_supported():
    t = SnappingTurtle(config={"active_gear": 5})
    df = synthetic_ohlcv(periods=10)
    try:
        t.on_data_received(df)  # type: ignore[arg-type]
        assert False, "expected TypeError"
    except TypeError:
        pass


def test_soul_runtime_flow_uses_two_arg_right_hemisphere_signature():
    o = Orchestrator.__new__(Orchestrator)
    o.config = {"execution_mode": "DRY_RUN"}
    o.run_id = "test-piece3"
    o.deadlines = {}
    o.pulse_log = []
    o.frame = BrainFrame()
    o.walk_engine = SimpleNamespace(
        build_seed=lambda **kwargs: None,
        calculate_regime_id=lambda *args, **kwargs: "R0",
    )
    o.furnace = SimpleNamespace(handle_pulse=lambda **kwargs: None)
    o.amygdala = SimpleNamespace(mint_synapse_ticket=lambda pulse_type, frame: None)
    o.pineal = SimpleNamespace(secrete_melatonin=lambda pulse_type: None)
    o.pituitary = SimpleNamespace(secrete_growth_hormone=lambda pulse_type: None)

    class Council:
        def consult(self, pulse_type, frame):
            frame.environment.atr = 1.0
            return frame.environment

        def get_state(self):
            return {"atr": 1.0}

    class Left:
        def on_data_received(self, pulse_type, frame):
            return False

    o.lobes = {
        "Right_Hemisphere": SnappingTurtle(config={"active_gear": 5}),
        "Council": Council(),
        "Left_Hemisphere": Left(),
    }
    df = synthetic_ohlcv(periods=10)
    df["pulse_type"] = "ACTION"
    o._process_frame(df)
    assert o.frame.structure.gear == 5
