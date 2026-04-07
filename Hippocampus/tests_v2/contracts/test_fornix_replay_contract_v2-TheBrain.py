from __future__ import annotations

from types import SimpleNamespace

import pandas as pd

from Cerebellum.Soul.brain_frame import BrainFrame
from Cerebellum.Soul.orchestrator import Orchestrator
from Hippocampus.Archivist.librarian import MultiTransportLibrarian as Librarian
from Hippocampus.amygdala import Amygdala
from Hippocampus.fornix import Fornix
from Hippocampus.tests_v2.fixtures.factories import temp_db_path


def _fornix_stub() -> Fornix:
    f = Fornix.__new__(Fornix)
    f.total_trades = 0
    f.total_bars_processed = 0
    f.total_mints = 0
    f.total_signals = 0
    f.shutdown_requested = False
    f.progress_callback = None
    f.start_time = None
    f.config = {
        "paths_per_lane": 2500,
        "risk_gate_paths_per_lane": 83,
        "valuation_paths": 2500,
        "chunk_size": 2,
        "checkpoint_interval": 1000,
        "max_hours": 8,
    }
    return f


class _PondStub:
    def __init__(self, bars: pd.DataFrame):
        self.bars = bars.copy()
        self.checkpoint = None
        self.checkpoints_saved = []
        self.synapse_batches = []
        self.after_ts_calls = []

    def get_checkpoint(self, symbol: str):
        return self.checkpoint

    def save_checkpoint(self, symbol: str, last_ts: str, bars_processed: int, mints_generated: int):
        self.checkpoint = {
            "last_ts": last_ts,
            "bars_processed": bars_processed,
            "mints_generated": mints_generated,
        }
        self.checkpoints_saved.append(dict(self.checkpoint))

    def get_bars_for_symbol(self, symbol: str, after_ts=None):
        self.after_ts_calls.append(after_ts)
        df = self.bars[self.bars["symbol"] == symbol].copy()
        if after_ts:
            df = df[df["ts"] > pd.Timestamp(after_ts)]
        return df.reset_index(drop=True)

    def write_synapse_batch(self, tickets):
        self.synapse_batches.append(list(tickets))


class _GlandStub:
    def ingest(self, chunk: pd.DataFrame):
        pulse_df = chunk.copy()
        return [("SEED", pulse_df), ("ACTION", pulse_df), ("MINT", pulse_df)]


def test_fornix_routes_pulse_materials_through_soul_with_canonical_fields():
    f = _fornix_stub()
    frame = BrainFrame()
    captured = []

    def _process_frame(df):
        captured.append(df.copy())
        frame.market.pulse_type = str(df["pulse_type"].iloc[-1])
        frame.market.symbol = str(df["symbol"].iloc[-1])
        frame.command.ready_to_fire = False

    soul = SimpleNamespace(frame=frame, _process_frame=_process_frame)
    pulse = pd.DataFrame(
        [{"open": 10.0, "high": 11.0, "low": 9.5, "close": 10.5, "volume": 1000.0}],
        index=pd.to_datetime(["2026-01-01 09:30:00"]),
    )

    out = f._route_pulse_through_soul("ACTION", pulse, "AAPL", soul)

    assert out is None
    assert len(captured) == 1
    seen = captured[0]
    assert seen["pulse_type"].iloc[-1] == "ACTION"
    assert seen["symbol"].iloc[-1] == "AAPL"


def test_fornix_mint_route_returns_snapshot_and_updates_trade_counter():
    f = _fornix_stub()
    frame = BrainFrame()
    frame.to_synapse_dict = lambda: {"pulse_type": "MINT", "symbol": "AAPL"}  # type: ignore[method-assign]

    def _process_frame(df):
        frame.command.ready_to_fire = True

    soul = SimpleNamespace(frame=frame, _process_frame=_process_frame)
    pulse = pd.DataFrame(
        [{"open": 10.0, "high": 11.0, "low": 9.5, "close": 10.5, "volume": 1000.0}],
        index=pd.to_datetime(["2026-01-01 09:35:00"]),
    )

    out = f._route_pulse_through_soul("MINT", pulse, "AAPL", soul)

    assert out == {"pulse_type": "MINT", "symbol": "AAPL"}
    assert f.total_trades == 1


def test_fornix_build_pipeline_propagates_backtest_mode(monkeypatch):
    f = _fornix_stub()
    registered = []

    class DummySoul:
        def __init__(self, config=None):
            self.config = config or {}
            self.mode = None

        def register_lobe(self, name, instance):
            registered.append((name, instance))

        def set_execution_mode(self, mode):
            self.mode = mode

    class DummySmartGland:
        def __init__(self, window_minutes=5, context_size=50):
            self.window_minutes = window_minutes
            self.context_size = context_size

    class DummyLobe:
        def __init__(self, config=None, mode=None):
            self.config = config or {}
            self.mode = mode

    class DummyTrigger:
        def __init__(self, api_key, api_secret, paper=True, config=None):
            self.api_key = api_key
            self.api_secret = api_secret
            self.paper = paper
            self.config = config or {}

    monkeypatch.setattr("Hippocampus.fornix.Orchestrator", DummySoul)
    monkeypatch.setattr("Hippocampus.fornix.SmartGland", DummySmartGland)
    monkeypatch.setattr("Hippocampus.fornix.SnappingTurtle", DummyLobe)
    monkeypatch.setattr("Hippocampus.fornix.Council", DummyLobe)
    monkeypatch.setattr("Hippocampus.fornix.TurtleMonte", DummyLobe)
    monkeypatch.setattr("Hippocampus.fornix.Callosum", DummyLobe)
    monkeypatch.setattr("Hippocampus.fornix.Gatekeeper", DummyLobe)
    monkeypatch.setattr("Hippocampus.fornix.Trigger", DummyTrigger)

    _, soul = f._build_pipeline(symbol="AAPL")

    names = [name for name, _ in registered]
    assert names == [
        "Right_Hemisphere",
        "Council",
        "Left_Hemisphere",
        "Corpus",
        "Gatekeeper",
        "Brain_Stem",
    ]
    assert soul.mode == "BACKTEST"
    assert soul.config.get("execution_mode") == "BACKTEST"
    assert all(instance.config.get("execution_mode") == "BACKTEST" for _, instance in registered)


def test_fornix_resume_uses_checkpoint_and_processes_only_remaining_bars():
    f = _fornix_stub()
    bars = pd.DataFrame(
        [
            {"ts": pd.Timestamp("2026-01-01 09:30:00"), "symbol": "AAPL", "open": 10.0, "high": 11.0, "low": 9.0, "close": 10.5, "volume": 1000.0},
            {"ts": pd.Timestamp("2026-01-01 09:31:00"), "symbol": "AAPL", "open": 10.5, "high": 11.2, "low": 10.2, "close": 10.8, "volume": 1001.0},
            {"ts": pd.Timestamp("2026-01-01 09:32:00"), "symbol": "AAPL", "open": 10.8, "high": 11.4, "low": 10.6, "close": 11.0, "volume": 1002.0},
            {"ts": pd.Timestamp("2026-01-01 09:33:00"), "symbol": "AAPL", "open": 11.0, "high": 11.5, "low": 10.9, "close": 11.2, "volume": 1003.0},
        ]
    )
    pond = _PondStub(bars)
    f.pond = pond
    f._build_pipeline = lambda symbol: (_GlandStub(), SimpleNamespace(frame=BrainFrame()))  # type: ignore[method-assign]

    seen_mints = []

    def _route(pulse_type, pulse_data, symbol, soul):
        if pulse_type != "MINT":
            return None
        seen_mints.append(str(pulse_data.index[-1]))
        return {"pulse_type": "MINT", "symbol": symbol, "ts": pulse_data.index[-1]}

    f._route_pulse_through_soul = _route  # type: ignore[method-assign]

    f._process_symbol("AAPL", 1, 1, resume=True)
    first_ckpt = pond.checkpoint
    assert first_ckpt is not None
    assert int(first_ckpt["bars_processed"]) == 4
    assert int(first_ckpt["mints_generated"]) == 2

    f._process_symbol("AAPL", 1, 1, resume=True)
    assert pond.after_ts_calls[0] is None
    assert pond.after_ts_calls[1] == first_ckpt["last_ts"]
    assert int(f.total_bars_processed) == 4
    assert int(f.total_mints) == 2
    assert len(seen_mints) == 2


def test_fornix_chunk_fault_isolated_and_checkpoint_remains_resumable():
    f = _fornix_stub()
    bars = pd.DataFrame(
        [
            {"ts": pd.Timestamp("2026-01-01 09:30:00"), "symbol": "AAPL", "open": 10.0, "high": 11.0, "low": 9.0, "close": 10.5, "volume": 1000.0},
            {"ts": pd.Timestamp("2026-01-01 09:31:00"), "symbol": "AAPL", "open": 10.5, "high": 11.2, "low": 10.2, "close": 10.8, "volume": 1001.0},
            {"ts": pd.Timestamp("2026-01-01 09:32:00"), "symbol": "AAPL", "open": 10.8, "high": 11.4, "low": 10.6, "close": 11.0, "volume": 1002.0},
            {"ts": pd.Timestamp("2026-01-01 09:33:00"), "symbol": "AAPL", "open": 11.0, "high": 11.5, "low": 10.9, "close": 11.2, "volume": 1003.0},
        ]
    )
    pond = _PondStub(bars)
    f.pond = pond
    f._build_pipeline = lambda symbol: (_GlandStub(), SimpleNamespace(frame=BrainFrame()))  # type: ignore[method-assign]

    state = {"failed_once": False}

    def _route(pulse_type, pulse_data, symbol, soul):
        if pulse_type == "ACTION" and not state["failed_once"]:
            state["failed_once"] = True
            return None
        if pulse_type == "MINT":
            return {"pulse_type": "MINT", "symbol": symbol, "ts": pulse_data.index[-1]}
        return None

    f._route_pulse_through_soul = _route  # type: ignore[method-assign]

    f._process_symbol("AAPL", 1, 1, resume=True)

    assert state["failed_once"] is True
    assert pond.checkpoint is not None
    assert int(pond.checkpoint["bars_processed"]) == 4
    assert int(pond.checkpoint["mints_generated"]) == 2
    assert int(f.total_mints) == 2


def test_fornix_mint_replay_persists_through_amygdala_with_machine_code():
    f = _fornix_stub()
    primary_db = temp_db_path("v2_fornix_primary")
    backtest_db = temp_db_path("v2_fornix_backtest")
    a = Amygdala(
        config={
            "synapse_db_path_primary": str(primary_db),
            "synapse_db_path_backtest": str(backtest_db),
        }
    )
    frame = BrainFrame()

    def _process_frame(df):
        frame.market.ohlcv = df
        frame.market.ts = df.index[-1]
        frame.market.symbol = str(df["symbol"].iloc[-1])
        frame.market.execution_mode = "BACKTEST"
        frame.market.pulse_type = "MINT"
        frame.structure.price = float(df["close"].iloc[-1])
        frame.structure.active_hi = float(df["high"].max())
        frame.structure.active_lo = float(df["low"].min())
        frame.structure.gear = 5
        frame.structure.tier1_signal = 1
        frame.risk.monte_score = 0.8
        frame.risk.tier_score = 0.7
        frame.risk.regime_id = "R1"
        frame.environment.confidence = 0.75
        frame.environment.atr = 1.2
        frame.environment.atr_avg = 1.0
        frame.environment.adx = 20.0
        frame.environment.volume_score = 0.9
        frame.command.reason = "APPROVED"
        frame.command.approved = 1
        frame.command.final_confidence = 0.75
        frame.command.sizing_mult = 1.0
        frame.command.ready_to_fire = True
        a.mint_synapse_ticket("MINT", frame)

    soul = SimpleNamespace(frame=frame, _process_frame=_process_frame)
    pulse = pd.DataFrame(
        [{"open": 10.0, "high": 11.0, "low": 9.5, "close": 10.5, "volume": 1000.0}],
        index=pd.to_datetime(["2026-01-01 09:35:00"]),
    )
    out = f._route_pulse_through_soul("MINT", pulse, "AAPL", soul)

    rows = Librarian(db_path=backtest_db).read_only(
        "SELECT machine_code, pulse_type, symbol FROM synapse_mint LIMIT 1"
    )
    assert out is not None
    assert rows
    assert rows[0]["pulse_type"] == "MINT"
    assert rows[0]["symbol"] == "AAPL"
    assert rows[0]["machine_code"] is not None
    assert str(backtest_db) == a.get_state()["last_target_db"]


def test_live_vs_backtest_pipeline_sequence_parity_on_same_bar_stream():
    events_live = []
    events_backtest = []

    class Right:
        def __init__(self, sink):
            self.sink = sink

        def on_data_received(self, pulse_type, frame):
            frame.structure.price = float(frame.market.ohlcv["close"].iloc[-1])
            frame.structure.active_lo = float(frame.market.ohlcv["low"].iloc[-1])
            frame.structure.tier1_signal = 1
            self.sink.append("Right_Hemisphere")

    class Council:
        def __init__(self, sink):
            self.sink = sink

        def consult(self, pulse_type, frame):
            frame.environment.atr = 1.0
            frame.environment.adx = 20.0
            self.sink.append("Council")

        def get_state(self):
            return {"atr": 1.0}

    class Left:
        def __init__(self, sink):
            self.sink = sink

        def on_data_received(self, pulse_type, frame):
            self.sink.append("Left_Hemisphere.on_data_received")
            return True

        def simulate(self, pulse_type, frame, walk_seed=None):
            self.sink.append("Left_Hemisphere.simulate")

    class Corpus:
        def __init__(self, sink):
            self.sink = sink

        def score_tier(self, pulse_type, frame):
            frame.risk.tier_score = 0.8
            self.sink.append("Corpus")

    class Gatekeeper:
        def __init__(self, sink):
            self.sink = sink

        def decide(self, pulse_type, frame):
            frame.command.ready_to_fire = pulse_type == "ACTION"
            frame.command.approved = int(frame.command.ready_to_fire)
            self.sink.append("Gatekeeper")

    class BrainStem:
        def __init__(self, sink):
            self.sink = sink

        def load_and_hunt(self, pulse_type, frame, orchestrator=None, walk_engine=None, walk_seed=None):
            self.sink.append("Brain_Stem")

    def _orchestrator(mode: str, sink: list) -> Orchestrator:
        o = Orchestrator.__new__(Orchestrator)
        o.config = {"execution_mode": mode}
        o.run_id = f"test-seq-{mode.lower()}"
        o.deadlines = {}
        o.pulse_log = []
        o.frame = BrainFrame()
        o.frame.market.execution_mode = mode
        o.walk_engine = SimpleNamespace(
            build_seed=lambda **kwargs: SimpleNamespace(regime_id="R0"),
            calculate_regime_id=lambda *args, **kwargs: "R0",
        )
        o.furnace = SimpleNamespace(handle_pulse=lambda **kwargs: kwargs["walk_seed"] and kwargs["walk_seed"])
        o.lobes = {
            "Right_Hemisphere": Right(sink),
            "Council": Council(sink),
            "Left_Hemisphere": Left(sink),
            "Corpus": Corpus(sink),
            "Gatekeeper": Gatekeeper(sink),
            "Brain_Stem": BrainStem(sink),
        }
        o.amygdala = SimpleNamespace(mint_synapse_ticket=lambda pulse_type, frame: None)
        o.pineal = SimpleNamespace(secrete_melatonin=lambda pulse_type: None)
        o.pituitary = SimpleNamespace(secrete_growth_hormone=lambda pulse_type: None)
        return o

    live_orch = _orchestrator("DRY_RUN", events_live)
    backtest_orch = _orchestrator("BACKTEST", events_backtest)
    f = _fornix_stub()

    for pulse in ("SEED", "ACTION", "MINT"):
        base = pd.DataFrame(
            [{"symbol": "AAPL", "open": 10.0, "high": 11.0, "low": 9.5, "close": 10.5, "volume": 1000.0}],
            index=pd.to_datetime(["2026-01-01 09:30:00"]),
        )
        live_df = base.copy()
        live_df["pulse_type"] = pulse
        live_orch._process_frame(live_df)

        replay_df = base.copy()
        f._route_pulse_through_soul(pulse, replay_df, "AAPL", backtest_orch)

    assert events_live == events_backtest
