from __future__ import annotations

from types import SimpleNamespace

import pandas as pd

from Cerebellum.Soul.brain_frame import BrainFrame
from Cerebellum.Soul.orchestrator import Orchestrator


def _df(pulse: str = "ACTION") -> pd.DataFrame:
    df = pd.DataFrame(
        [{"symbol": "BTC/USD", "open": 100.0, "high": 101.0, "low": 99.0, "close": 100.5, "volume": 10.0, "pulse_type": pulse}],
        index=pd.to_datetime(["2026-01-01 12:00:00"]),
    )
    return df


def _orch(mode: str = "DRY_RUN") -> Orchestrator:
    o = Orchestrator.__new__(Orchestrator)
    o.config = {"execution_mode": mode}
    o.run_id = f"piece16-{mode.lower()}"
    o.deadlines = {}
    o.lobes = {}
    o.pulse_log = []
    o.pulse_seq = 0
    o.frame = BrainFrame()
    o.frame.market.execution_mode = mode
    o.last_action_ts = None
    o.walk_engine = SimpleNamespace(
        build_seed=lambda **kwargs: SimpleNamespace(regime_id="R1", mutations=[0.1], support_floor_ok=True),
        calculate_regime_id=lambda *args, **kwargs: "R1",
    )
    o.furnace = SimpleNamespace(handle_frame=lambda **kwargs: None)
    o.amygdala = SimpleNamespace(mint_synapse_ticket=lambda pulse_type, frame: None)
    o.pineal = SimpleNamespace(secrete_melatonin=lambda pulse_type: None)
    o.pituitary = SimpleNamespace(secrete_growth_hormone=lambda pulse_type: None)
    o._check_vault_mutation = lambda: None
    return o


def test_brainframe_schema_contains_piece16_canonical_fields():
    f = BrainFrame()
    assert hasattr(f.market, "execution_mode")
    assert hasattr(f.market, "pulse_type")
    for k in ("mu", "sigma", "p_jump", "shocks", "regime_id", "monte_score", "tier_score", "lane_survivals"):
        assert hasattr(f.risk, k)


def test_brainframe_flatten_includes_machine_code_and_risk_fields():
    f = BrainFrame()
    df = _df("MINT")
    f.market.ohlcv = df
    f.market.ts = df.index[-1]
    f.market.symbol = "BTC/USD"
    f.market.execution_mode = "BACKTEST"
    f.market.pulse_type = "MINT"
    f.risk.mu = 0.01
    f.risk.sigma = 0.2
    f.risk.p_jump = 0.05
    f.risk.regime_id = "R2"
    out = f.to_synapse_dict()
    assert out["machine_code"]
    assert out["execution_mode"] == "BACKTEST"
    assert out["mu"] == 0.01
    assert out["sigma"] == 0.2
    assert out["p_jump"] == 0.05
    assert out["regime_id"] == "R2"


def test_soul_lobe_order_is_deterministic_and_dependency_safe():
    o = _orch("DRY_RUN")
    order = []

    class Right:
        def on_data_received(self, pulse_type, frame):
            order.append("Right")
            frame.structure.price = 100.5
            frame.structure.active_lo = 99.0
            frame.structure.tier1_signal = 1

    class Council:
        def consult(self, pulse_type, frame):
            order.append("Council")
            frame.environment.atr = 1.0
            frame.environment.confidence = 0.8

        def get_state(self):
            return {"atr": 1.0}

    class Left:
        def on_data_received(self, pulse_type, frame):
            order.append("Left.on_data_received")
            return True

        def simulate(self, pulse_type, frame, walk_seed=None):
            order.append("Left.simulate")

    class Corpus:
        def score_tier(self, pulse_type, frame):
            order.append("Corpus")

    class Gatekeeper:
        def decide(self, pulse_type, frame):
            order.append("Gatekeeper")
            frame.command.ready_to_fire = True
            frame.command.approved = 1

    class BrainStem:
        def load_and_hunt(self, pulse_type, frame, orchestrator=None, walk_engine=None, walk_seed=None):
            order.append(f"BrainStem:{pulse_type}")

    o.lobes = {
        "Right_Hemisphere": Right(),
        "Council": Council(),
        "Left_Hemisphere": Left(),
        "Corpus": Corpus(),
        "Gatekeeper": Gatekeeper(),
        "Brain_Stem": BrainStem(),
    }
    o._process_frame(_df("ACTION"))
    assert order == [
        "Right",
        "Council",
        "Left.on_data_received",
        "Left.simulate",
        "Corpus",
        "Gatekeeper",
        "BrainStem:ACTION",
    ]


def test_soul_stamps_mode_and_pulse_before_lobe_work():
    o = _orch("PAPER")
    seen = {}

    class Right:
        def on_data_received(self, pulse_type, frame):
            seen["pulse"] = frame.market.pulse_type
            seen["mode"] = frame.market.execution_mode
            frame.structure.price = 100.0
            frame.structure.active_lo = 99.0

    class Council:
        def consult(self, pulse_type, frame):
            frame.environment.atr = 1.0

        def get_state(self):
            return {"atr": 1.0}

    class Left:
        def on_data_received(self, pulse_type, frame):
            return False

    o.lobes = {"Right_Hemisphere": Right(), "Council": Council(), "Left_Hemisphere": Left()}
    o._process_frame(_df("SEED"))
    assert seen["pulse"] == "SEED"
    assert seen["mode"] == "PAPER"


def test_constructor_and_register_lobe_smoke(monkeypatch):
    import Cerebellum.Soul.orchestrator as mod

    monkeypatch.setattr(mod, "WardManager", lambda: SimpleNamespace(janitor_sweep=lambda: None))
    monkeypatch.setattr(mod, "VolumeFurnaceOrchestrator", lambda **kwargs: SimpleNamespace(handle_frame=lambda **kw: None, set_execution_mode=lambda m: None))
    monkeypatch.setattr(mod, "Amygdala", lambda: SimpleNamespace(mint_synapse_ticket=lambda pulse_type, frame: None))
    monkeypatch.setattr(mod, "Pineal", lambda: SimpleNamespace(secrete_melatonin=lambda pulse_type: None))
    monkeypatch.setattr(mod, "PituitaryGland", lambda: SimpleNamespace(secrete_growth_hormone=lambda pulse_type: None))
    monkeypatch.setattr(mod, "librarian", SimpleNamespace(get_hormonal_vault=lambda: {"gold": {"id": "v1", "params": {}}}))
    monkeypatch.setattr(mod, "QuantizedGeometricWalk", lambda: SimpleNamespace(build_seed=lambda **k: None))
    o = Orchestrator(config={"execution_mode": "DRY_RUN"})

    class L:
        def __init__(self):
            self.config = {}
            self.mode = "LIVE"

    l = L()
    o.register_lobe("Right_Hemisphere", l)
    assert "Right_Hemisphere" in o.lobes
    assert o.lobes["Right_Hemisphere"].mode == "DRY_RUN"


def test_legacy_lobe_signature_is_not_accepted_without_adapter():
    o = _orch("DRY_RUN")
    called = {"legacy": 0}

    class LegacyRight:
        def on_data_received(self, frame):  # legacy shape (missing pulse arg)
            called["legacy"] += 1

    class Council:
        def consult(self, pulse_type, frame):
            frame.environment.atr = 1.0

        def get_state(self):
            return {"atr": 1.0}

    class Left:
        def on_data_received(self, pulse_type, frame):
            return False

    o.lobes = {"Right_Hemisphere": LegacyRight(), "Council": Council(), "Left_Hemisphere": Left()}
    o._process_frame(_df("ACTION"))
    assert called["legacy"] == 0


def test_mint_hook_order_and_failure_isolation():
    o = _orch("DRY_RUN")
    events = []

    class Right:
        def on_data_received(self, pulse_type, frame):
            frame.structure.price = 100.0
            frame.structure.active_lo = 99.0

    class Council:
        def consult(self, pulse_type, frame):
            frame.environment.atr = 1.0

        def get_state(self):
            return {"atr": 1.0}

    class Left:
        def on_data_received(self, pulse_type, frame):
            return False

    o.lobes = {"Right_Hemisphere": Right(), "Council": Council(), "Left_Hemisphere": Left(), "Brain_Stem": SimpleNamespace(load_and_hunt=lambda *a, **k: None)}
    o.amygdala = SimpleNamespace(mint_synapse_ticket=lambda pulse_type, frame: (_ for _ in ()).throw(RuntimeError("amygdala fail")))
    o.pineal = SimpleNamespace(secrete_melatonin=lambda pulse_type: events.append("pineal"))
    o._check_vault_mutation = lambda: events.append("reload")
    o.pituitary = SimpleNamespace(secrete_growth_hormone=lambda pulse_type: events.append("pituitary"))
    o._process_frame(_df("MINT"))
    assert events == ["pineal", "reload", "pituitary"]
    assert o.pulse_log[-1]["hooks"]["amygdala"].startswith("error:")
    assert o.pulse_log[-1]["hooks"]["pituitary"] == "ok"


def test_action_to_mint_30s_timing_guard_deterministic(monkeypatch):
    o = _orch("DRY_RUN")
    events = []

    class Right:
        def on_data_received(self, pulse_type, frame):
            frame.structure.price = 100.0
            frame.structure.active_lo = 99.0
            frame.structure.tier1_signal = 1

    class Council:
        def consult(self, pulse_type, frame):
            frame.environment.atr = 1.0
            frame.environment.confidence = 0.9

        def get_state(self):
            return {"atr": 1.0}

    class Left:
        def on_data_received(self, pulse_type, frame):
            return True

        def simulate(self, pulse_type, frame, walk_seed=None):
            return None

    class Corpus:
        def score_tier(self, pulse_type, frame):
            frame.risk.tier_score = 0.9

    class Gate:
        def decide(self, pulse_type, frame):
            frame.command.ready_to_fire = True
            frame.command.approved = 1
            frame.command.reason = "APPROVED"

    class Brain:
        def load_and_hunt(self, pulse_type, frame, orchestrator=None, walk_engine=None, walk_seed=None):
            events.append((pulse_type, frame.command.reason, frame.command.ready_to_fire))

    o.lobes = {
        "Right_Hemisphere": Right(),
        "Council": Council(),
        "Left_Hemisphere": Left(),
        "Corpus": Corpus(),
        "Gatekeeper": Gate(),
        "Brain_Stem": Brain(),
    }
    seq = iter([1000.0, 1031.0])
    monkeypatch.setattr("Cerebellum.Soul.orchestrator.time.time", lambda: next(seq))
    o._process_frame(_df("ACTION"))
    o._process_frame(_df("MINT"))
    assert any(e[0] == "MINT" and "TIMING_CANCEL" in e[1] and e[2] is False for e in events)


def test_four_mode_parity_and_no_orchestration_drift():
    for mode in ("DRY_RUN", "PAPER", "LIVE", "BACKTEST"):
        o = _orch(mode)

        class Right:
            def on_data_received(self, pulse_type, frame):
                frame.structure.price = 100.0
                frame.structure.active_lo = 99.0

        class Council:
            def consult(self, pulse_type, frame):
                frame.environment.atr = 1.0

            def get_state(self):
                return {"atr": 1.0}

        class Left:
            def on_data_received(self, pulse_type, frame):
                return False

        o.lobes = {"Right_Hemisphere": Right(), "Council": Council(), "Left_Hemisphere": Left()}
        o._process_frame(_df("SEED"))
        assert o.frame.market.execution_mode == mode
        assert o.frame.market.pulse_type == "SEED"
        assert o.pulse_log[-1]["mode"] == mode


def test_lobe_cannot_advance_lifecycle_pulse_outside_soul():
    o = _orch("DRY_RUN")

    class Right:
        def on_data_received(self, pulse_type, frame):
            frame.structure.price = 100.0
            frame.structure.active_lo = 99.0
            frame.market.pulse_type = "MINT"  # malicious mutation attempt

    class Council:
        def consult(self, pulse_type, frame):
            frame.environment.atr = 1.0

        def get_state(self):
            return {"atr": 1.0}

    class Left:
        def on_data_received(self, pulse_type, frame):
            return False

    o.lobes = {"Right_Hemisphere": Right(), "Council": Council(), "Left_Hemisphere": Left()}
    o._process_frame(_df("ACTION"))
    assert o.frame.market.pulse_type == "ACTION"
