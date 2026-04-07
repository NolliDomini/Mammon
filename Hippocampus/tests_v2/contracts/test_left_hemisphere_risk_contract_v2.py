from types import SimpleNamespace

from Cerebellum.Soul.brain_frame import BrainFrame
from Cerebellum.Soul.orchestrator import Orchestrator
from Left_Hemisphere.Monte_Carlo.quantized_geometric_walk import QuantizedGeometricWalk
from Left_Hemisphere.Monte_Carlo.turtle_monte import TurtleMonte
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
    f.environment.atr = 1.5
    f.environment.atr_avg = 1.2
    f.environment.confidence = 0.7
    return f


def test_walk_paints_mu_sigma_pjump_and_regime_on_frame_each_cycle():
    f = _frame()
    walk = QuantizedGeometricWalk(mode="LIVE")
    walk.scribe = SimpleNamespace(discharge=lambda regime_id, limit=35000: [0.1, -0.1, 0.05])
    council_state = {
        "confidence": 0.7,
        "inputs": {"close": f.structure.price, "avwap": f.structure.price - 0.5, "atr": 1.5, "atr_avg": 1.2, "volume": 2000.0, "vol_avg": 1000.0, "adx": 35.0},
    }
    seed = walk.build_seed(council_state=council_state, pulse_type="ACTION", run_id="test-walk", frame=f)
    assert seed.regime_id == f.risk.regime_id
    assert f.risk.mu != 0.0 or f.risk.sigma != 0.0
    assert f.risk.sigma > 0.0
    assert f.risk.p_jump >= 0.0
    assert len(f.risk.shocks) > 0


def test_monte_reads_frame_priors_and_writes_only_risk_outputs():
    f = _frame()
    f.risk.mu = 0.02
    f.risk.sigma = 1.1
    f.risk.p_jump = 0.03
    f.risk.regime_id = "R_TEST"
    f.risk.shocks = [0.01, -0.02, 0.03]
    m = TurtleMonte(config={"paths_per_lane": 50}, mode="LIVE")

    before_market = f.market.__dict__.copy()
    before_structure = f.structure.__dict__.copy()
    before_env = f.environment.__dict__.copy()
    before_cmd = f.command.__dict__.copy()
    score = m.simulate("ACTION", frame=f)
    assert score >= 0.0
    assert before_market == f.market.__dict__
    assert before_structure == f.structure.__dict__
    assert before_env == f.environment.__dict__
    assert before_cmd == f.command.__dict__
    assert isinstance(f.risk.lane_survivals, list)
    assert len(f.risk.lane_survivals) == 3


def test_live_backtest_shock_path_parity_with_same_shock_buffer():
    shocks = [0.02, -0.01, 0.03, -0.02, 0.01]
    f_live = _frame("LIVE")
    f_back = _frame("BACKTEST")
    for f in (f_live, f_back):
        f.risk.mu = 0.01
        f.risk.sigma = 1.0
        f.risk.p_jump = 0.0
        f.risk.regime_id = "R_PARITY"
        f.risk.shocks = shocks
    m = TurtleMonte(config={"paths_per_lane": 40}, mode="LIVE")
    s_live = m.simulate("ACTION", frame=f_live)
    s_back = m.simulate("ACTION", frame=f_back)
    assert abs(s_live - s_back) < 1e-12


def test_deterministic_fallback_when_shock_buffers_missing_or_undersized():
    f1 = _frame()
    f1.risk.mu = 0.01
    f1.risk.sigma = 1.0
    f1.risk.p_jump = 0.02
    f1.risk.regime_id = "R_FALLBACK"
    f1.risk.shocks = []
    m = TurtleMonte(config={"paths_per_lane": 25}, mode="LIVE")
    s1 = m.simulate("ACTION", frame=f1)

    f2 = _frame()
    f2.risk.mu = 0.01
    f2.risk.sigma = 1.0
    f2.risk.p_jump = 0.02
    f2.risk.regime_id = "R_FALLBACK"
    f2.risk.shocks = []
    s2 = m.simulate("ACTION", frame=f2)
    assert abs(s1 - s2) < 1e-12

    f3 = _frame()
    f3.risk.mu = 0.01
    f3.risk.sigma = 1.0
    f3.risk.p_jump = 0.0
    f3.risk.regime_id = "R_UNDERSIZED"
    f3.risk.shocks = [0.1]
    s3 = m.simulate("ACTION", frame=f3)
    assert s3 >= 0.0


def test_left_hemisphere_modules_do_not_own_pulse_schedule():
    f = _frame()
    m = TurtleMonte(config={"paths_per_lane": 20})
    assert m.on_data_received("NON_CANONICAL_PULSE", frame=f) is True
    walk = QuantizedGeometricWalk(mode="LIVE")
    walk.scribe = SimpleNamespace(discharge=lambda regime_id, limit=35000: [])
    seed = walk.build_seed(council_state={"inputs": {}}, pulse_type="NON_CANONICAL_PULSE", frame=f)
    assert seed is not None


def test_soul_runtime_wiring_excludes_legacy_monte_entrypoint():
    class MonteNoLegacy(TurtleMonte):
        def _simulate_legacy(self, *args, **kwargs):
            raise AssertionError("legacy simulate path should not be called in Soul runtime flow")

    o = Orchestrator.__new__(Orchestrator)
    o.config = {"execution_mode": "DRY_RUN", "trading_enabled_provider": lambda: False}
    o.run_id = "piece4-runtime"
    o.deadlines = {}
    o.pulse_log = []
    o.frame = BrainFrame()
    o.walk_engine = SimpleNamespace(
        build_seed=lambda **kwargs: SimpleNamespace(regime_id="R4", mu=0.01, sigma=1.0, p_jump=0.0, mutations=[0.1, -0.1]),
        calculate_regime_id=lambda *args, **kwargs: "R4",
    )
    o.furnace = SimpleNamespace(handle_pulse=lambda **kwargs: None)
    o.amygdala = SimpleNamespace(mint_synapse_ticket=lambda pulse_type, frame: None)
    o.pineal = SimpleNamespace(secrete_melatonin=lambda pulse_type: None)
    o.pituitary = SimpleNamespace(secrete_growth_hormone=lambda pulse_type: None)

    class Right:
        def on_data_received(self, pulse_type, frame):
            frame.structure.price = float(frame.market.ohlcv["close"].iloc[-1])
            frame.structure.active_lo = float(frame.market.ohlcv["low"].iloc[-5:].min())
            frame.structure.gear = 5
            frame.structure.tier1_signal = 1
            return frame.market.ohlcv, []

    class Council:
        def consult(self, pulse_type, frame):
            frame.environment.atr = 1.5
            frame.environment.confidence = 0.7
            return frame.environment

        def get_state(self):
            return {"inputs": {"atr": 1.5, "atr_avg": 1.2, "close": 100.0, "avwap": 99.5, "volume": 2000.0, "vol_avg": 1000.0, "adx": 30.0}}

    class Gatekeeper:
        def decide(self, pulse_type, frame):
            frame.command.ready_to_fire = False
            return frame.command

    class Corpus:
        def score_tier(self, pulse_type, frame):
            frame.risk.tier_score = 0.5
            return frame.risk

    left = MonteNoLegacy(config={"paths_per_lane": 20})
    o.lobes = {"Right_Hemisphere": Right(), "Council": Council(), "Left_Hemisphere": left, "Corpus": Corpus(), "Gatekeeper": Gatekeeper()}
    df = synthetic_ohlcv(periods=20)
    df["pulse_type"] = "ACTION"
    o._process_frame(df)
    assert left.legacy_simulation_calls == 0


def test_fail_safe_on_malformed_frame_inputs():
    m = TurtleMonte(config={"paths_per_lane": 20})

    f_atr0 = _frame()
    f_atr0.environment.atr = 0.0
    assert m.simulate("ACTION", frame=f_atr0) == 0.0

    f_nostop = _frame()
    f_nostop.structure.active_lo = None
    assert m.simulate("ACTION", frame=f_nostop) == 0.0

    f_nogear = _frame()
    f_nogear.structure.gear = 0
    assert m.simulate("ACTION", frame=f_nogear) == 0.0
