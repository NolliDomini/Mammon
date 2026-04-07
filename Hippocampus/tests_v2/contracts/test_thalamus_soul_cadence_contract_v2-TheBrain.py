from types import SimpleNamespace

from Cerebellum.Soul.orchestrator import Orchestrator
from Cerebellum.Soul.brain_frame import BrainFrame
from Thalamus.relay import Thalamus
from Hippocampus.tests_v2.fixtures.factories import synthetic_ohlcv


class _RightStub:
    def on_data_received(self, pulse_type, frame):
        frame.structure.price = float(frame.market.ohlcv["close"].iloc[-1])
        frame.structure.tier1_signal = 0
        return frame.market.ohlcv, []


class _CouncilStub:
    def consult(self, pulse_type, frame):
        frame.environment.atr = 1.0
        frame.environment.confidence = 0.5
        return frame.environment

    def get_state(self):
        return {"atr": 1.0, "confidence": 0.5}


class _LeftStub:
    def on_data_received(self, pulse_type, frame):
        return False


def _orch(mode: str) -> Orchestrator:
    o = Orchestrator.__new__(Orchestrator)
    o.config = {"execution_mode": mode}
    o.run_id = f"test-soul-{mode.lower()}"
    o.deadlines = {}
    o.pulse_log = []
    o.frame = BrainFrame()
    o.frame.market.execution_mode = mode
    o.walk_engine = SimpleNamespace(
        build_seed=lambda **kwargs: None,
        calculate_regime_id=lambda *args, **kwargs: "R0",
    )
    o.furnace = SimpleNamespace(handle_pulse=lambda **kwargs: None)
    o.lobes = {
        "Right_Hemisphere": _RightStub(),
        "Council": _CouncilStub(),
        "Left_Hemisphere": _LeftStub(),
    }
    o.amygdala = SimpleNamespace(mint_synapse_ticket=lambda pulse_type, frame: None)
    o.pineal = SimpleNamespace(secrete_melatonin=lambda pulse_type: None)
    o.pituitary = SimpleNamespace(secrete_growth_hormone=lambda pulse_type: None)
    return o


def test_soul_applies_seed_action_mint_cadence_without_schema_branching():
    t = Thalamus()
    raw = synthetic_ohlcv(start="2026-01-01 12:00:00", periods=10, freq="1min")
    pulses = t.drip_pulse(raw)
    names = [name for name, _ in pulses]
    assert "SEED" in names
    assert "ACTION" in names
    assert "MINT" in names

    o = _orch("DRY_RUN")
    base_cols = None
    for pulse_name, df in pulses:
        cols_wo_pulse = [c for c in df.columns if c != "pulse_type"]
        if base_cols is None:
            base_cols = cols_wo_pulse
        assert cols_wo_pulse == base_cols
        o._process_frame(df)
        assert o.frame.market.pulse_type == pulse_name


def test_ingestion_schema_parity_is_identical_across_runtime_modes():
    t = Thalamus()
    raw = synthetic_ohlcv(start="2026-01-01 13:00:00", periods=7, freq="1min")
    pulses = t.drip_pulse(raw)
    pulse_df = pulses[1][1]  # ACTION frame
    expected_cols = tuple(pulse_df.columns)

    for mode in ("DRY_RUN", "PAPER", "LIVE", "BACKTEST"):
        o = _orch(mode)
        o._process_frame(pulse_df)
        assert tuple(o.frame.market.ohlcv.columns) == expected_cols
