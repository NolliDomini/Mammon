from types import SimpleNamespace

from Cerebellum.Soul.brain_frame import BrainFrame
from Cerebellum.Soul.orchestrator import Orchestrator
from Corpus.callosum import Callosum
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
    f.risk.monte_score = 0.8
    f.environment.confidence = 0.7
    f.environment.atr = 1.5
    return f


def test_callosum_mutates_only_frame_risk_tier_score():
    f = _frame()
    c = Callosum(config={"callosum_w_monte": 0.7, "callosum_w_right": 0.3})
    before_market = f.market.__dict__.copy()
    before_structure = f.structure.__dict__.copy()
    before_env = f.environment.__dict__.copy()
    before_cmd = f.command.__dict__.copy()
    before_risk = f.risk.__dict__.copy()

    pkt = c.score_tier("ACTION", f)

    assert pkt.tier_score == f.risk.tier_score
    assert before_market == f.market.__dict__
    assert before_structure == f.structure.__dict__
    assert before_env == f.environment.__dict__
    assert before_cmd == f.command.__dict__

    risk_after = f.risk.__dict__.copy()
    for k, v in before_risk.items():
        if k == "tier_score":
            continue
        assert risk_after[k] == v


def test_callosum_score_is_deterministic_for_same_frame_and_config():
    f1 = _frame()
    f2 = _frame()
    cfg = {"callosum_w_monte": 0.65, "callosum_w_right": 0.35}
    c = Callosum(config=cfg)
    s1 = c.score_tier("ACTION", f1).tier_score
    s2 = c.score_tier("ACTION", f2).tier_score
    assert abs(s1 - s2) < 1e-12


def test_callosum_malformed_inputs_fail_safe_to_deterministic_score():
    f = _frame()
    f.risk.monte_score = float("nan")
    f.structure.tier1_signal = float("inf")
    c = Callosum(config={"callosum_w_monte": 1.0, "callosum_w_right": 1.0})
    pkt = c.score_tier("ACTION", f)
    assert pkt.tier_score == 0.0
    assert f.risk.tier_score == 0.0


def test_soul_flow_gatekeeper_receives_populated_tier_score_before_decide():
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
            frame.environment.confidence = 0.8
            return frame.environment

        def get_state(self):
            return {"inputs": {"atr": 1.2, "atr_avg": 1.0, "close": 100.0, "avwap": 99.5, "volume": 2000.0, "vol_avg": 1000.0, "adx": 30.0}}

    class Left:
        def on_data_received(self, pulse_type, frame):
            frame.risk.monte_score = 0.8
            return True

        def simulate(self, pulse_type, frame, walk_seed=None):
            frame.risk.monte_score = 0.8
            return 0.8

    seen = {"score_before_decide": False}

    class Gatekeeper:
        def decide(self, pulse_type, frame):
            seen["score_before_decide"] = frame.risk.tier_score > 0.0
            frame.command.ready_to_fire = False
            return frame.command

    o = Orchestrator.__new__(Orchestrator)
    o.config = {"execution_mode": "DRY_RUN", "trading_enabled_provider": lambda: False}
    o.run_id = "piece5-runtime"
    o.deadlines = {}
    o.pulse_log = []
    o.frame = BrainFrame()
    o.walk_engine = SimpleNamespace(
        build_seed=lambda **kwargs: SimpleNamespace(regime_id="R5", mu=0.01, sigma=1.0, p_jump=0.0, mutations=[0.1, -0.1]),
        calculate_regime_id=lambda *args, **kwargs: "R5",
    )
    o.furnace = SimpleNamespace(handle_pulse=lambda **kwargs: None)
    o.amygdala = SimpleNamespace(mint_synapse_ticket=lambda pulse_type, frame: None)
    o.pineal = SimpleNamespace(secrete_melatonin=lambda pulse_type: None)
    o.pituitary = SimpleNamespace(secrete_growth_hormone=lambda pulse_type: None)
    o.lobes = {
        "Right_Hemisphere": Right(),
        "Council": Council(),
        "Left_Hemisphere": Left(),
        "Corpus": Callosum(config={"callosum_w_monte": 1.0, "callosum_w_right": 0.0}),
        "Gatekeeper": Gatekeeper(),
    }

    df = synthetic_ohlcv(periods=20)
    df["pulse_type"] = "ACTION"
    o._process_frame(df)
    assert seen["score_before_decide"] is True


def test_soul_runtime_wiring_uses_frame_contract_not_legacy_call_shapes():
    class RuntimeContractOnlyCallosum(Callosum):
        def __init__(self):
            super().__init__()
            self.runtime_calls = 0
            self.legacy_shape_seen = 0

        def score_tier(self, pulse_type, frame):
            self.runtime_calls += 1
            if not isinstance(pulse_type, str) or frame is None:
                self.legacy_shape_seen += 1
            return super().score_tier(pulse_type, frame)

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
            frame.environment.confidence = 0.8
            return frame.environment

        def get_state(self):
            return {"inputs": {"atr": 1.2, "atr_avg": 1.0, "close": 100.0, "avwap": 99.5, "volume": 2000.0, "vol_avg": 1000.0, "adx": 30.0}}

    class Left:
        def on_data_received(self, pulse_type, frame):
            frame.risk.monte_score = 0.8
            return True

        def simulate(self, pulse_type, frame, walk_seed=None):
            frame.risk.monte_score = 0.8
            return 0.8

    class Gatekeeper:
        def decide(self, pulse_type, frame):
            frame.command.ready_to_fire = False
            return frame.command

    corpus = RuntimeContractOnlyCallosum()

    o = Orchestrator.__new__(Orchestrator)
    o.config = {"execution_mode": "DRY_RUN", "trading_enabled_provider": lambda: False}
    o.run_id = "piece5-contract"
    o.deadlines = {}
    o.pulse_log = []
    o.frame = BrainFrame()
    o.walk_engine = SimpleNamespace(
        build_seed=lambda **kwargs: SimpleNamespace(regime_id="R5", mu=0.01, sigma=1.0, p_jump=0.0, mutations=[0.1, -0.1]),
        calculate_regime_id=lambda *args, **kwargs: "R5",
    )
    o.furnace = SimpleNamespace(handle_pulse=lambda **kwargs: None)
    o.amygdala = SimpleNamespace(mint_synapse_ticket=lambda pulse_type, frame: None)
    o.pineal = SimpleNamespace(secrete_melatonin=lambda pulse_type: None)
    o.pituitary = SimpleNamespace(secrete_growth_hormone=lambda pulse_type: None)
    o.lobes = {
        "Right_Hemisphere": Right(),
        "Council": Council(),
        "Left_Hemisphere": Left(),
        "Corpus": corpus,
        "Gatekeeper": Gatekeeper(),
    }

    df = synthetic_ohlcv(periods=20)
    df["pulse_type"] = "ACTION"
    o._process_frame(df)

    assert corpus.runtime_calls == 1
    assert corpus.legacy_shape_seen == 0


def test_callosum_logging_failure_is_isolated_from_runtime_output():
    f = _frame()
    c = Callosum(config={"callosum_w_monte": 1.0, "callosum_w_right": 0.0})
    c.librarian = SimpleNamespace(dispatch=lambda *args, **kwargs: (_ for _ in ()).throw(RuntimeError("db down")))
    pkt = c.score_tier("ACTION", f)
    assert pkt.tier_score == 0.8
    assert f.risk.tier_score == 0.8

