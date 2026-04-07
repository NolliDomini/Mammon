from types import SimpleNamespace

from Cerebellum.Soul.brain_frame import BrainFrame
from Cerebellum.Soul.orchestrator import Orchestrator
from Medulla.gatekeeper import Gatekeeper
from Hippocampus.tests_v2.fixtures.factories import synthetic_ohlcv


def _frame(mode: str = "DRY_RUN") -> BrainFrame:
    f = BrainFrame()
    df = synthetic_ohlcv(periods=20)
    f.market.ohlcv = df
    f.market.ts = df.index[-1]
    f.market.symbol = "BTC/USD"
    f.market.pulse_type = "ACTION"
    f.market.execution_mode = mode
    f.structure.price = float(df["close"].iloc[-1])
    f.structure.active_lo = float(df["low"].iloc[-5:].min())
    f.structure.gear = 5
    f.structure.tier1_signal = 1
    f.risk.tier_score = 0.9
    f.environment.confidence = 0.9
    return f


def test_gatekeeper_only_action_can_fire():
    g = Gatekeeper(config={"gatekeeper_min_monte": 0.6, "gatekeeper_min_council": 0.5})
    for pulse in ("SEED", "MINT", "ACTION"):
        f = _frame()
        out = g.decide(pulse, f)
        if pulse == "ACTION":
            assert out.ready_to_fire is True
            assert out.approved == 1
            assert out.reason == "APPROVED"
        else:
            assert out.ready_to_fire is False
            assert out.approved == 0
            assert out.reason == "INHIBIT_PULSE_ILLEGAL"


def test_gatekeeper_mutates_only_frame_command():
    f = _frame()
    g = Gatekeeper()
    before_market = f.market.__dict__.copy()
    before_structure = f.structure.__dict__.copy()
    before_risk = f.risk.__dict__.copy()
    before_env = f.environment.__dict__.copy()
    _ = g.decide("ACTION", f)
    assert before_market == f.market.__dict__
    assert before_structure == f.structure.__dict__
    assert before_risk == f.risk.__dict__
    assert before_env == f.environment.__dict__
    assert isinstance(f.command.ready_to_fire, bool)


def test_gatekeeper_mode_aware_policy_across_four_modes():
    g = Gatekeeper(config={"gatekeeper_min_monte": 0.6, "gatekeeper_min_council": 0.5})
    for mode in ("DRY_RUN", "PAPER", "LIVE", "BACKTEST"):
        f = _frame(mode)
        out = g.decide("ACTION", f)
        assert out.ready_to_fire is True
        assert out.approved == 1
        assert out.reason == "APPROVED"

    f_bad = _frame("WARMUP")
    out_bad = g.decide("ACTION", f_bad)
    assert out_bad.ready_to_fire is False
    assert out_bad.reason == "INHIBIT_MODE_GATE"


def test_gatekeeper_reason_taxonomy_and_threshold_boundary_semantics():
    g = Gatekeeper(config={"gatekeeper_min_monte": 0.8, "gatekeeper_min_council": 0.5, "gatekeeper_threshold_cmp": ">"})

    f_equal = _frame()
    f_equal.risk.tier_score = 0.8
    out_equal = g.decide("ACTION", f_equal)
    assert out_equal.reason == "INHIBIT_THRESHOLD_TIER"

    f_council = _frame()
    f_council.environment.confidence = 0.1
    out_council = g.decide("ACTION", f_council)
    assert out_council.reason == "INHIBIT_THRESHOLD_COUNCIL"

    f_ok = _frame()
    out_ok = g.decide("ACTION", f_ok)
    assert out_ok.reason == "APPROVED"

    assert hasattr(out_ok, "ready_to_fire")
    assert hasattr(out_ok, "approved")
    assert hasattr(out_ok, "reason")
    assert hasattr(out_ok, "final_confidence")
    assert hasattr(out_ok, "sizing_mult")


def test_soul_runtime_wiring_excludes_legacy_evaluate_entrypoint():
    class RuntimeContractOnlyGatekeeper(Gatekeeper):
        def __init__(self):
            super().__init__()
            self.decide_calls = 0
            self.evaluate_calls = 0

        def decide(self, pulse_type, frame):
            self.decide_calls += 1
            return super().decide(pulse_type, frame)

        def evaluate(self, signal):
            self.evaluate_calls += 1
            raise AssertionError("legacy evaluate path should not be called in Soul runtime flow")

    class Right:
        def on_data_received(self, pulse_type, frame):
            frame.structure.price = float(frame.market.ohlcv["close"].iloc[-1])
            frame.structure.active_lo = float(frame.market.ohlcv["low"].iloc[-5:].min())
            frame.structure.gear = 5
            frame.structure.tier1_signal = 1
            return frame.market.ohlcv, []

    class Council:
        def consult(self, pulse_type, frame):
            frame.environment.atr = 1.2
            frame.environment.confidence = 0.9
            return frame.environment

        def get_state(self):
            return {"inputs": {"atr": 1.2, "atr_avg": 1.0, "close": 100.0, "avwap": 99.5, "volume": 2000.0, "vol_avg": 1000.0, "adx": 30.0}}

    class Left:
        def on_data_received(self, pulse_type, frame):
            frame.risk.monte_score = 0.8
            return True

        def simulate(self, pulse_type, frame, walk_seed=None):
            frame.risk.monte_score = 0.8
            frame.risk.tier_score = 0.8
            return 0.8

    class Corpus:
        def score_tier(self, pulse_type, frame):
            frame.risk.tier_score = 0.8
            return frame.risk

    gate = RuntimeContractOnlyGatekeeper()

    o = Orchestrator.__new__(Orchestrator)
    o.config = {"execution_mode": "DRY_RUN", "trading_enabled_provider": lambda: False}
    o.run_id = "piece6-runtime"
    o.deadlines = {}
    o.pulse_log = []
    o.frame = BrainFrame()
    o.walk_engine = SimpleNamespace(
        build_seed=lambda **kwargs: SimpleNamespace(regime_id="R6", mu=0.01, sigma=1.0, p_jump=0.0, mutations=[0.1, -0.1]),
        calculate_regime_id=lambda *args, **kwargs: "R6",
    )
    o.furnace = SimpleNamespace(handle_pulse=lambda **kwargs: None)
    o.amygdala = SimpleNamespace(mint_synapse_ticket=lambda pulse_type, frame: None)
    o.pineal = SimpleNamespace(secrete_melatonin=lambda pulse_type: None)
    o.pituitary = SimpleNamespace(secrete_growth_hormone=lambda pulse_type: None)
    o.lobes = {
        "Right_Hemisphere": Right(),
        "Council": Council(),
        "Left_Hemisphere": Left(),
        "Corpus": Corpus(),
        "Gatekeeper": gate,
    }

    df = synthetic_ohlcv(periods=20)
    df["pulse_type"] = "ACTION"
    o._process_frame(df)

    assert gate.decide_calls == 1
    assert gate.evaluate_calls == 0


def test_gatekeeper_logging_failure_isolated_from_decision():
    g = Gatekeeper(config={"gatekeeper_min_monte": 0.6, "gatekeeper_min_council": 0.5})
    g.librarian = SimpleNamespace(dispatch=lambda *args, **kwargs: (_ for _ in ()).throw(RuntimeError("db down")))
    f = _frame()
    out = g.decide("ACTION", f)
    assert out.ready_to_fire is True
    assert out.reason == "APPROVED"

