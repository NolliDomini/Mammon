"""Mammon Dashboard Backend (v4.0 Clean).
Flask API for the Mammon neural trading engine.
Provides: start/stop, SSE pulse stream, treasury KPIs, vault params.
"""
import os
import sys
import json
import time
import queue
import threading
import traceback
import uuid
from collections import deque
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Dict, Optional
from datetime import datetime, timezone

from flask import Flask, request, jsonify, Response, send_from_directory, render_template_string
from dotenv import load_dotenv

# Ensure project root is importable
ROOT_DIR = Path(__file__).resolve().parent
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from Hippocampus.Context.mner import emit_mner, read_mner_tail

load_dotenv()

# ------------------------------------------------------------------ #
#  APP & AUTH                                                          #
# ------------------------------------------------------------------ #
DASHBOARD_DIR = ROOT_DIR / "dashboard"
app = Flask(__name__, static_folder=str(DASHBOARD_DIR), static_url_path="/static")
API_BEARER_TOKEN = os.environ.get("MAMMON_API_TOKEN", "dev-token")
STOP_ON_WINDOW_CLOSE = str(os.environ.get("MAMMON_STOP_ON_WINDOW_CLOSE", "1")).strip().lower() in {
    "1",
    "true",
    "yes",
    "on",
}
ENGINE_LIFECYCLE_LOG_PATH = ROOT_DIR / "runtime" / "logs" / "engine_lifecycle.jsonl"
_engine_lifecycle_log_lock = threading.Lock()
_rate_buckets: Dict[str, list] = {}


def _clip(value: Any, maxlen: int = 240) -> str:
    return str(value or "")[:maxlen]


def _utc_iso_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _write_engine_lifecycle_event(event_type: str, **fields) -> None:
    record = {"ts": _utc_iso_now(), "event": event_type}
    record.update(fields)
    try:
        ENGINE_LIFECYCLE_LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
        with _engine_lifecycle_log_lock:
            with ENGINE_LIFECYCLE_LOG_PATH.open("a", encoding="utf-8") as fp:
                fp.write(json.dumps(record, ensure_ascii=True) + "\n")
    except Exception as e:
        emit_mner(
            "MNER-W-INFRA-003",
            "ENGINE_LIFECYCLE_LOG_WRITE_FAILED",
            source="dashboard._write_engine_lifecycle_event",
            details={"event_type": event_type, "error": _safe_str(e)},
        )
        print(f"[DASHBOARD] lifecycle log write failed: {_safe_str(e)}")


def _read_engine_lifecycle_tail(limit: int = 100) -> list:
    if limit <= 0:
        return []
    if not ENGINE_LIFECYCLE_LOG_PATH.exists():
        return []
    ring = deque(maxlen=min(limit, 500))
    try:
        with ENGINE_LIFECYCLE_LOG_PATH.open("r", encoding="utf-8") as fp:
            for line in fp:
                line = line.strip()
                if not line:
                    continue
                try:
                    ring.append(json.loads(line))
                except Exception:
                    continue
    except Exception:
        return []
    return list(ring)

def _require_infra():
    """Fail hard if required infra is missing."""
    try:
        from Hippocampus.Archivist.librarian import librarian
        redis_conn = librarian.get_redis_connection()
        redis_conn.ping()
        ts_conn = librarian.get_timescale_connection()
        try:
            ts_conn.rollback()
        except Exception:
            pass
        with ts_conn.cursor() as cur:
            cur.execute("SELECT 1")
            cur.fetchone()
    except Exception as e:
        emit_mner(
            "MNER-E-INFRA-001",
            "REQUIRED_INFRA_MISSING",
            source="dashboard._require_infra",
            details={"error": _safe_str(e, 500)},
        )
        raise RuntimeError(f"[MNER-E-INFRA-001] REQUIRED_INFRA_MISSING: {e}")


def _extract_bearer():
    auth = request.headers.get("Authorization", "")
    if auth.startswith("Bearer "):
        return auth[7:].strip()
    return request.args.get("token", "").strip()


@app.before_request
def _auth_gate():
    if request.path.startswith("/api/"):
        token = _extract_bearer()
        if token != API_BEARER_TOKEN:
            return jsonify({"error": "unauthorized"}), 401
    return None


@app.route("/__health")
def health():
    return "ok", 200, {"Cache-Control": "no-store"}


@app.route("/__shutdown", methods=["POST"])
def shutdown():
    """Request server shutdown."""
    func = request.environ.get("werkzeug.server.shutdown")
    if func is None:
        # Not running with the development server, just exit
        threading.Thread(target=lambda: (time.sleep(0.5), os._exit(0))).start()
    else:
        func()
    return "", 204


@app.after_request
def _cors_headers(response):
    """Add CORS headers on API responses (safety net for decoupled setups)."""
    if request.path.startswith("/api/"):
        response.headers["Access-Control-Allow-Origin"] = "*"
        response.headers["Access-Control-Allow-Headers"] = "Authorization, Content-Type"
        response.headers["Access-Control-Allow-Methods"] = "GET, POST, OPTIONS"
    return response


# ------------------------------------------------------------------ #
#  ENGINE STATE                                                        #
# ------------------------------------------------------------------ #
class EngineState:
    """Thread-safe engine state container."""

    def __init__(self):
        self.running = False
        self.thread: Optional[threading.Thread] = None
        self.symbols: list = []
        self.active_symbol: Optional[str] = None
        self.bars_processed = 0
        self.run_id: Optional[str] = None
        self.started_at: Optional[float] = None
        self.last_started_at: Optional[float] = None
        self.last_stopped_at: Optional[float] = None
        self.last_run_duration_sec: float = 0.0
        self.lock = threading.Lock()

        # SSE queues (one queue per connected client)
        self.sse_clients: list[queue.Queue] = []

        # Mode gates
        self.mode = "DRY_RUN"
        self.trading_enabled = True
        self.kill_switch = "ARMED"  # ARMED | TRIPPED
        self.live_unlock_token: Optional[str] = None

        # Live references (set inside _engine_loop)
        self.orchestrator = None
        self.trigger = None
        self.thalamus = None
        self.last_frame_dict: Optional[dict] = None
        self._stream_loop = None  # asyncio loop for the WebSocket stream thread

        # Lifecycle forensics
        self.stop_requested = False
        self.stop_requested_at: Optional[float] = None
        self.stop_source = ""
        self.stop_reason = ""
        self.stop_detail = ""
        self.last_exit_kind = "NEVER_STARTED"
        self.last_exit_source = ""
        self.last_exit_reason = ""
        self.last_exit_detail = ""
        self.last_exit_at: Optional[float] = None
        self.last_exception_type = ""
        self.last_exception_msg = ""
        self.last_exception_traceback = ""

    def push_event(self, event_type: str, data: dict):
        """Push event to SSE listeners. Non-blocking."""
        event = {
            "type": event_type,
            "data": data,
            "ts": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        }
        stale_clients: list[queue.Queue] = []
        with self.lock:
            clients = list(self.sse_clients)
        for client_q in clients:
            try:
                client_q.put_nowait(event)
            except queue.Full:
                try:
                    client_q.get_nowait()
                    client_q.put_nowait(event)
                except Exception:
                    stale_clients.append(client_q)
            except Exception:
                stale_clients.append(client_q)

        if stale_clients:
            with self.lock:
                for client_q in stale_clients:
                    if client_q in self.sse_clients:
                        self.sse_clients.remove(client_q)

    def request_stop(self, source: str, reason: str, detail: str = ""):
        """Record stop intent and lower the run flag."""
        self.stop_requested = True
        self.stop_requested_at = time.time()
        self.stop_source = _clip(source, 80) or "unknown"
        self.stop_reason = _clip(reason, 120) or "unspecified"
        self.stop_detail = _clip(detail, 240)
        self.running = False


state = EngineState()


# ------------------------------------------------------------------ #
#  FORNIX STATE                                                        #
# ------------------------------------------------------------------ #
class FornixState:
    """Thread-safe state container for the Fornix backtest engine."""

    def __init__(self):
        self.running = False
        self.thread: Optional[threading.Thread] = None
        self.run_id: Optional[str] = None
        self.started_at: Optional[float] = None
        self.current_symbol: Optional[str] = None
        self.bars_done: int = 0
        self.total_bars: int = 0
        self.mints: int = 0
        self.signals: int = 0
        self.bars_per_sec: float = 0.0
        self.eta_minutes: float = 0.0
        self.last_exit: str = "NEVER_STARTED"
        self.error: str = ""
        self.fornix = None
        self.combo_index: int = 0
        self.lock = threading.Lock()


fornix_state = FornixState()


def _fornix_loop(full: bool, symbols: Optional[list], run_id: str) -> None:
    """Background thread that runs the Fornix replay engine."""
    # Suspend live trading for the duration of the backtest
    with state.lock:
        was_trading = state.trading_enabled
        state.trading_enabled = False
    state.push_event("system", {"msg": "Trading suspended — backtest running"})

    try:
        from Hippocampus.fornix.service import Fornix, TEST_PULSE_25, TEST_PULSE_FULL

        pulse = TEST_PULSE_FULL if full else TEST_PULSE_25

        def _progress(symbol, bars_done, total_bars, mints, signals, bars_per_sec, eta_minutes):
            with fornix_state.lock:
                fornix_state.current_symbol = symbol
                fornix_state.bars_done = bars_done
                fornix_state.total_bars = total_bars
                fornix_state.mints = mints
                fornix_state.signals = signals
                fornix_state.bars_per_sec = bars_per_sec
                fornix_state.eta_minutes = eta_minutes
            pct = round(bars_done / total_bars * 100, 1) if total_bars > 0 else 0.0
            state.push_event("fornix_progress", {
                "symbol": symbol,
                "bars_done": bars_done,
                "total_bars": total_bars,
                "mints": mints,
                "signals": signals,
                "bars_per_sec": round(bars_per_sec, 1),
                "eta_minutes": round(eta_minutes, 1),
                "run_id": run_id,
            })
            # Also push to neural log so the user sees the engine is alive.
            state.push_event("system", {
                "msg": f"FORNIX {symbol} | {bars_done:,}/{total_bars:,} ({pct}%) | {round(bars_per_sec,1)}/s | MINTs:{mints} | ETA:{round(eta_minutes,1)}m"
            })

        f = Fornix(test_pulse=pulse, progress_callback=_progress)
        with fornix_state.lock:
            fornix_state.fornix = f

        state.push_event("fornix_lifecycle", {
            "lifecycle": "STARTED",
            "run_id": run_id,
            "full": full,
            "msg": f"Fornix started ({'FULL' if full else 'TEST_PULSE_25'})",
        })

        f.run(symbols=symbols)

        with fornix_state.lock:
            fornix_state.last_exit = "COMPLETE"

        state.push_event("fornix_lifecycle", {
            "lifecycle": "STOPPED",
            "run_id": run_id,
            "msg": "Fornix replay complete",
            "bars": getattr(f, "total_bars_processed", 0),
            "mints": getattr(f, "total_mints", 0),
            "signals": getattr(f, "total_signals", 0),
            "trades": getattr(f, "total_trades", 0),
        })

    except Exception as e:
        tb = traceback.format_exc(limit=20)
        with fornix_state.lock:
            fornix_state.last_exit = "CRASH"
            fornix_state.error = _safe_str(e, 400)
        state.push_event("fornix_lifecycle", {
            "lifecycle": "STOPPED",
            "run_id": run_id,
            "exit_kind": "CRASH",
            "msg": f"Fornix crash: {_safe_str(e)}",
            "error": _safe_str(e, 400),
        })
        print(f"[FORNIX] Crash: {e}")
        print(tb)
    finally:
        with state.lock:
            state.trading_enabled = was_trading
        state.push_event("system", {"msg": "Trading resumed — backtest complete"})
        with fornix_state.lock:
            if fornix_state.run_id == run_id:
                fornix_state.running = False
                fornix_state.fornix = None
                fornix_state.thread = None


# ------------------------------------------------------------------ #
#  COMBO CYCLING & FORNIX JOB HELPERS                                 #
# ------------------------------------------------------------------ #
def _get_next_combo() -> Optional[list]:
    """
    Picks the next (stock, crypto) combo from DuckDB market_tape symbols, cycling each call.
    Stocks = anything without '/' and not ending _USD/USDT/USDC.
    Cryptos = everything with '/' or those suffixes.
    Returns a list like ['AAPL', 'BTC/USD'], or None if nothing in DuckDB.
    """
    try:
        import duckdb as _duckdb
        _duck_path = str(Path(__file__).resolve().parent / "Hospital" / "Memory_care" / "duck.db")
        _con = _duckdb.connect(_duck_path)
        try:
            rows = _con.execute("SELECT DISTINCT symbol FROM market_tape ORDER BY symbol").fetchall()
        finally:
            try:
                _con.close()
            except Exception:
                pass
        all_syms = [r[0] for r in rows]
    except Exception as e:
        print(f"[COMBO] DuckDB unavailable: {e}")
        return None

    cryptos = [s for s in all_syms if "/" in s or s.upper().endswith(("_USD", "_USDT", "_USDC"))]
    stocks  = [s for s in all_syms if s not in cryptos]

    with fornix_state.lock:
        idx = fornix_state.combo_index
        fornix_state.combo_index += 1

    combo = []
    if stocks:
        combo.append(stocks[idx % len(stocks)])
    if cryptos:
        combo.append(cryptos[idx % len(cryptos)])
    return combo or None


def _start_fornix_job(full: bool, symbols: Optional[list], source: str = "api") -> Optional[str]:
    """Start Fornix in a background thread. Returns run_id or None if already running."""
    with fornix_state.lock:
        if fornix_state.running:
            return None
        run_id = uuid.uuid4().hex
        fornix_state.running = True
        fornix_state.run_id = run_id
        fornix_state.started_at = time.time()
        fornix_state.current_symbol = None
        fornix_state.bars_done = 0
        fornix_state.total_bars = 0
        fornix_state.mints = 0
        fornix_state.signals = 0
        fornix_state.bars_per_sec = 0.0
        fornix_state.eta_minutes = 0.0
        fornix_state.last_exit = "RUNNING"
        fornix_state.error = ""

    t = threading.Thread(
        target=_fornix_loop,
        args=(full, symbols, run_id),
        daemon=True,
        name=f"mammon-fornix-{source}-{run_id[:8]}",
    )
    with fornix_state.lock:
        fornix_state.thread = t
    t.start()
    return run_id


def _midnight_fornix_job() -> None:
    """
    APScheduler midnight job.
    Always fires regardless of engine mode — suspends live trading
    for the duration of the replay (handled inside _fornix_loop).
    """
    if fornix_state.running:
        print("[SCHEDULER] Midnight Fornix skipped — Fornix already active.")
        return
    combo = _get_next_combo()
    if not combo:
        print("[SCHEDULER] Midnight Fornix skipped — no symbols in market_tape.")
        return
    run_id = _start_fornix_job(full=False, symbols=combo, source="midnight")
    if run_id:
        print(f"[SCHEDULER] Midnight Fornix fired: run_id={run_id[:8]}, symbols={combo}")
        state.push_event("fornix_lifecycle", {
            "lifecycle": "SCHEDULED_START",
            "run_id": run_id,
            "msg": f"Midnight backtest started: {combo}",
            "symbols": combo,
        })
    else:
        print("[SCHEDULER] Midnight Fornix: could not start (race).")


# ------------------------------------------------------------------ #
#  HELPERS                                                             #
# ------------------------------------------------------------------ #
def _safe_str(e, maxlen=200):
    return str(e)[:maxlen]


def _is_crypto_symbol(symbol: str) -> bool:
    s = symbol.upper()
    return "/" in s or s.endswith(("_USD", "_USDT", "_USDC"))


def _normalize_symbol(symbol: str) -> str:
    s = (symbol or "").strip().upper().replace(" ", "")
    if "_" in s:
        base, quote = s.rsplit("_", 1)
        if base and quote in {"USD", "USDT", "USDC"}:
            return f"{base}/{quote}"
    return s


def _bar_to_dict(bar_obj, symbol):
    """Extract OHLCV from an Alpaca bar payload to a 1-row DataFrame."""
    import pandas as pd

    if bar_obj is None:
        return None, None

    # Unwrap dict/object
    if isinstance(bar_obj, dict):
        obj = bar_obj.get(symbol) or next(iter(bar_obj.values()), None)
    elif hasattr(bar_obj, "data") and isinstance(bar_obj.data, dict):
        obj = bar_obj.data.get(symbol) or next(iter(bar_obj.data.values()), None)
    else:
        obj = bar_obj

    if obj is None:
        return None, None

    def _field(o, *names):
        if isinstance(o, dict):
            for n in names:
                if n in o and o[n] is not None:
                    return o[n]
        else:
            for n in names:
                v = getattr(o, n, None)
                if v is not None:
                    return v
        return None

    ts = _field(obj, "timestamp", "time", "t")
    o = _field(obj, "open", "o")
    h = _field(obj, "high", "h")
    lo = _field(obj, "low", "l")
    c = _field(obj, "close", "c")
    v = _field(obj, "volume", "v")

    if any(x is None for x in (ts, o, h, lo, c, v)):
        return None, None

    ts = pd.to_datetime(ts, errors="coerce", utc=True)
    if pd.isna(ts):
        return None, None
    ts = ts.tz_convert(None)

    row = {
        "open": float(o), "high": float(h), "low": float(lo),
        "close": float(c), "volume": float(v), "symbol": symbol,
    }
    return pd.DataFrame([row], index=[ts]), ts


def _frame_to_event(frame, symbol, pulse_type, mode, bar_dict=None) -> dict:
    """Convert BrainFrame snapshot to a flat event dict for SSE."""
    valuation_slot = getattr(frame, "valuation", None)
    execution_slot = getattr(frame, "execution", None)
    event = {
        "symbol": symbol,
        "pulse_type": pulse_type,
        "mode": mode,
        "price": round(getattr(frame.structure, "price", 0), 4),
        "active_hi": round(getattr(frame.structure, "active_hi", 0), 4),
        "active_lo": round(getattr(frame.structure, "active_lo", 0), 4),
        "gear": int(getattr(frame.structure, "gear", 0) or 0),
        "tier1_signal": int(getattr(frame.structure, "tier1_signal", 0) or 0),
        # Environment
        "council_score": round(getattr(frame.environment, "confidence", 0), 3),
        "atr": round(getattr(frame.environment, "atr", 0), 6),
        "atr_avg": round(getattr(frame.environment, "atr_avg", 0), 6),
        "adx": round(getattr(frame.environment, "adx", 0), 3),
        "volume_score": round(getattr(frame.environment, "volume_score", 0), 3),
        "bid_ask_bps": round(getattr(frame.environment, "bid_ask_bps", 0), 2),
        "spread_score": round(getattr(frame.environment, "spread_score", 0), 3),
        "spread_regime": str(getattr(frame.environment, "spread_regime", "UNKNOWN")),
        # Risk
        "monte_score": round(getattr(frame.risk, "monte_score", 0), 3),
        "tier_score": round(getattr(frame.risk, "tier_score", 0), 3),
        "mu": round(getattr(frame.risk, "mu", 0), 8),
        "sigma": round(getattr(frame.risk, "sigma", 0), 8),
        "p_jump": round(getattr(frame.risk, "p_jump", 0), 8),
        "regime_id": str(getattr(frame.risk, "regime_id", "UNK")),
        "worst_survival": round(getattr(frame.risk, "worst_survival", 0), 4),
        "neutral_survival": round(getattr(frame.risk, "neutral_survival", 0), 4),
        "best_survival": round(getattr(frame.risk, "best_survival", 0), 4),
        # Valuation
        "val_mean": round(getattr(valuation_slot, "mean", 0), 4),
        "val_std_dev": round(getattr(valuation_slot, "std_dev", 0), 4),
        "val_z_distance": round(getattr(valuation_slot, "z_distance", 0), 4),
        # Execution
        "exec_expected_slippage_bps": round(getattr(execution_slot, "expected_slippage_bps", 0), 2),
        "exec_total_cost_bps": round(getattr(execution_slot, "total_cost_bps", 0), 2),
        # Command
        "approved": getattr(frame.command, "approved", 0),
        "ready_to_fire": int(bool(getattr(frame.command, "ready_to_fire", False))),
        "reason": str(getattr(frame.command, "reason", "")),
        "final_confidence": round(getattr(frame.command, "final_confidence", 0), 4),
        "sizing_mult": round(getattr(frame.command, "sizing_mult", 0), 6),
        "qty": round(getattr(frame.command, "qty", 0), 6),
        "notional": round(getattr(frame.command, "notional", 0), 2),
        "size_reason": str(getattr(frame.command, "size_reason", "NONE")),
        "cost_adjusted_conviction": round(getattr(frame.command, "cost_adjusted_conviction", 0), 4),
        "risk_used": round(getattr(frame.command, "risk_used", 0), 6),
    }
    # Attach OHLCV bar data for the chart
    if bar_dict:
        event.update(bar_dict)
    return event


# ------------------------------------------------------------------ #
#  ENGINE LOOP                                                         #
# ------------------------------------------------------------------ #
def _engine_loop(symbols: list, is_crypto_map: dict):
    """Background thread: polls Alpaca for latest bars, feeds through the full pipeline."""
    crash_exc: Optional[Exception] = None
    crash_traceback = ""
    run_id = "unknown"
    current_mode = "DRY_RUN"
    furnace = None  # populated after orchestrator init; referenced in finally for shutdown
    try:
        from Thalamus.relay.service import Thalamus
        from Cerebellum.Soul.orchestrator.service import Orchestrator
        from Corpus.Optical_Tract.spray import OpticalTract
        from Right_Hemisphere.Snapping_Turtle.engine.service import SnappingTurtle
        from Cerebellum.council.service import Council
        from Left_Hemisphere.Monte_Carlo.turtle.service import TurtleMonte
        from Corpus.callosum.service import Callosum
        from Medulla.gatekeeper.service import Gatekeeper
        from Brain_Stem.trigger.service import Trigger
        from Hippocampus.telepathy.service import Telepathy
        from Brain_Stem.pons_execution_cost.service import PonsExecutionCost
        from Medulla.allocation_gland.service import AllocationGland

        # Initialize Async persistence (Scribe Daemon)
        _telepathy = Telepathy()

        with state.lock:
            current_mode = state.mode
            run_id = state.run_id or "unknown"

        persist_pulses_env = os.environ.get("MAMMON_DECISION_PERSIST_PULSES", "SEED,ACTION,MINT")
        persist_pulses = [p.strip().upper() for p in persist_pulses_env.split(",") if p.strip()]
        if not persist_pulses:
            persist_pulses = ["MINT"]

        # Build Optical Tract → Soul subscription
        tract = OpticalTract()

        orchestrator = Orchestrator(
            optical_tract=tract,
            config={
                "trading_enabled_provider": lambda: state.trading_enabled,
                "execution_mode": current_mode,
                "synapse_persist_pulse_types": persist_pulses,
            },
        )

        # Register all lobes
        gold = orchestrator.vault.get("gold", {}).get("params", {})
        orchestrator.register_lobe("Right_Hemisphere", SnappingTurtle(config=dict(gold)))
        orchestrator.register_lobe("Council", Council(config=dict(gold), mode=current_mode))
        orchestrator.register_lobe("Left_Hemisphere", TurtleMonte(config=dict(gold), mode=current_mode))
        orchestrator.register_lobe("Corpus", Callosum(config=dict(gold), mode=current_mode))
        orchestrator.register_lobe("Gatekeeper", Gatekeeper(config=dict(gold), mode=current_mode))
        orchestrator.register_lobe("PonsExecutionCost", PonsExecutionCost())
        orchestrator.register_lobe("AllocationGland", AllocationGland())
        orchestrator.register_lobe(
            "Brain_Stem",
            Trigger(
                api_key=os.environ.get("ALPACA_API_KEY"),
                api_secret=os.environ.get("ALPACA_API_SECRET"),
                paper=(current_mode != "LIVE"),
                config={
                    "execution_mode": current_mode,
                    "max_notional_per_order": float(os.environ.get("MAMMON_MAX_NOTIONAL_PER_ORDER", "0") or 0),
                    "max_open_positions": int(os.environ.get("MAMMON_MAX_OPEN_POSITIONS", "0") or 0),
                    "max_daily_realized_loss": float(os.environ.get("MAMMON_MAX_DAILY_REALIZED_LOSS", "0") or 0),
                    **gold,
                },
            ),
        )

        # Build Thalamus with Optical Tract
        thalamus = Thalamus(
            api_key=os.environ.get("ALPACA_API_KEY"),
            api_secret=os.environ.get("ALPACA_API_SECRET"),
            optical_tract=tract,
        )
        orchestrator.register_lobe("Thalamus", thalamus)

        with state.lock:
            state.orchestrator = orchestrator
            state.trigger = orchestrator.lobes.get("Brain_Stem")
            state.thalamus = thalamus

        state.push_event("engine", {
            "msg": f"Engine started in mode={current_mode}",
            "lifecycle": "STARTED",
            "run_id": run_id,
        })
        _write_engine_lifecycle_event(
            "ENGINE_STARTED",
            run_id=run_id,
            mode=current_mode,
            symbols=symbols,
        )
        print(f"[DASHBOARD] Engine started: run_id={run_id}, mode={current_mode}, symbols={symbols}")

        furnace = getattr(orchestrator, "furnace", None)
        furnace_telemetry = getattr(furnace, "telemetry", None) if furnace is not None else None
        last_furnace_telemetry_len = len(furnace_telemetry) if isinstance(furnace_telemetry, list) else 0
        last_furnace_logged_activation = int(getattr(furnace, "activation_count", 0) or 0)

        def _publish_furnace_run_events(symbol_hint: str):
            nonlocal last_furnace_telemetry_len, last_furnace_logged_activation
            furnace_obj = getattr(orchestrator, "furnace", None)
            if furnace_obj is None:
                return
            telemetry = getattr(furnace_obj, "telemetry", None)
            if not isinstance(telemetry, list):
                return
            if len(telemetry) <= last_furnace_telemetry_len:
                return

            new_events = telemetry[last_furnace_telemetry_len : len(telemetry)]
            last_furnace_telemetry_len = len(telemetry)

            for evt in new_events:
                if not isinstance(evt, dict):
                    continue
                decision = str(evt.get("decision", "")).upper()
                if decision not in {"EXECUTED", "PIPELINE_ERROR"}:
                    continue

                mint_count = int(evt.get("mint", 0) or 0)
                activation_count = int(evt.get("activation", 0) or 0)
                if activation_count <= last_furnace_logged_activation:
                    continue
                last_furnace_logged_activation = activation_count

                error_msg = str(evt.get("error", "") or "")
                msg = f"FURNACE | {decision}"

                state.push_event(
                    "furnace",
                    {
                        "msg": msg,
                        "symbol": symbol_hint,
                        "decision": decision,
                        "mint_count": mint_count,
                        "activation_count": activation_count,
                        "error": error_msg,
                    },
                )

        # ── Warmup: prime SmartGland context concurrently with boundary wait ──
        _is_crypto_first = next(iter(is_crypto_map.values()), True)
        _warmup_thread = threading.Thread(
            target=lambda: thalamus.warmup_context(symbols, is_crypto=_is_crypto_first),
            daemon=True,
            name="mammon-warmup",
        )
        _warmup_thread.start()

        # ── Wait for the nearest 5-minute boundary ──
        import math
        now_ts = time.time()
        target = math.ceil(now_ts / 300) * 300
        wait_sec = max(target - time.time(), 0)
        
        state.push_event("system", {
            "msg": f"Syncing to 5m boundary — waiting {wait_sec:.0f}s",
        })
        print(f"[DASHBOARD] Waiting {wait_sec:.0f}s for next 5m boundary")
        next_wait_event_at = time.time() + 30.0
        while wait_sec > 0 and state.running and state.run_id == run_id:
            time.sleep(min(1.0, wait_sec))
            wait_sec = max(target - time.time(), 0)
            now_wait = time.time()
            if now_wait >= next_wait_event_at:
                state.push_event("system", {
                    "msg": f"Syncing to 5m boundary — waiting {wait_sec:.0f}s",
                    "type": "BOUNDARY_WAIT",
                    "seconds_remaining": int(wait_sec),
                })
                next_wait_event_at = now_wait + 30.0
            
        if not state.running or state.run_id != run_id:
            return

        state.push_event("system", {"msg": "Boundary reached — pipeline live"})
        print("[DASHBOARD] Boundary reached — starting live stream")
        _warmup_thread.join(timeout=30.0)

        # ── Live WebSocket stream ──
        import asyncio as _asyncio

        _stream_errors: list = []
        _stream_loop = _asyncio.new_event_loop()
        with state.lock:
            state._stream_loop = _stream_loop
        _last_bs_exec_ts = [""]  # mutable container so the async closure can update it

        async def _on_live_bar(bar) -> None:
            if not state.running:
                return
            symbol = getattr(bar, "symbol", symbols[0] if symbols else "")
            with state.lock:
                state.active_symbol = symbol
                loop_mode = state.mode
            try:
                import pandas as _pd
                raw_dict = {
                    "ts": bar.timestamp,
                    "open": float(bar.open),
                    "high": float(bar.high),
                    "low": float(bar.low),
                    "close": float(bar.close),
                    "volume": float(bar.volume),
                    "symbol": symbol,
                }
                raw_df = _pd.DataFrame([raw_dict])
                raw_df["ts"] = _pd.to_datetime(raw_df["ts"], utc=True)
                raw_df = raw_df.set_index("ts")
                bar_ts = raw_df.index[0]

                pulses = thalamus.drip_pulse(raw_df)
                _publish_furnace_run_events(symbol)

                with state.lock:
                    state.bars_processed += 1

                if pulses:
                    frame = orchestrator.frame
                    for pulse_type, pulse_df in pulses:
                        if not pulse_df.empty and {"open", "high", "low", "close", "volume"}.issubset(pulse_df.columns):
                            pr = pulse_df.iloc[-1]
                            pulse_bar_dict = {
                                "bar_time": int(bar_ts.timestamp()),
                                "bar_open": round(float(pr["open"]), 4),
                                "bar_high": round(float(pr["high"]), 4),
                                "bar_low": round(float(pr["low"]), 4),
                                "bar_close": round(float(pr["close"]), 4),
                                "bar_volume": round(float(pr["volume"]), 2),
                            }
                        else:
                            pulse_bar_dict = {
                                "bar_time": int(bar_ts.timestamp()),
                                "bar_open": round(float(raw_df.iloc[0]["open"]), 4),
                                "bar_high": round(float(raw_df.iloc[0]["high"]), 4),
                                "bar_low": round(float(raw_df.iloc[0]["low"]), 4),
                                "bar_close": round(float(raw_df.iloc[0]["close"]), 4),
                                "bar_volume": round(float(raw_df.iloc[0]["volume"]), 2),
                            }
                        event_data = _frame_to_event(
                            frame, symbol, pulse_type, loop_mode,
                            bar_dict=pulse_bar_dict,
                        )
                        with state.lock:
                            state.last_frame_dict = event_data
                        state.push_event("pulse", event_data)

                # Push ARM / FIRE / EXIT / REJECT / CANCEL to SSE so the log shows them
                _bs = orchestrator.lobes.get("Brain_Stem")
                if _bs is not None:
                    _exec = getattr(_bs, "last_execution_event", {})
                    _exec_ts = str(_exec.get("ts", ""))
                    if _exec_ts and _exec_ts != _last_bs_exec_ts[0]:
                        _last_bs_exec_ts[0] = _exec_ts
                        if str(_exec.get("transition", "")).upper() in {
                            "ARM", "FIRE", "EXIT", "REJECT", "CANCEL"
                        }:
                            state.push_event("execution", {**_exec, "symbol": symbol})

            except Exception as e:
                emit_mner(
                    "THAL-E-CONN-001",
                    "DATA_CONNECTION_DROP",
                    source="dashboard._on_live_bar",
                    details={"symbol": symbol, "error": _safe_str(e, 300)},
                    echo=True,
                )
                try:
                    bs = orchestrator.lobes.get("Brain_Stem")
                    if bs and bs.pending_entry:
                        intent_id = bs.pending_entry.get("intent_id")
                        if intent_id and bs.treasury:
                            bs.treasury.cancel_intent(intent_id, symbol, "DATA_CONNECTION_DROP")
                        bs.pending_entry = None
                        bs.mean_dev_monitor_active = False
                except Exception:
                    pass
                state.push_event("error", {"symbol": symbol, "msg": _safe_str(e)})

        def _run_stream() -> None:
            try:
                _asyncio.set_event_loop(_stream_loop)
                _stream_loop.run_until_complete(
                    thalamus.connect_stream(symbols, _is_crypto_first, bar_callback=_on_live_bar)
                )
            except Exception as e:
                _stream_errors.append(e)

        _stream_thread = threading.Thread(target=_run_stream, daemon=True, name="mammon-stream")
        _stream_thread.start()

        while state.running and state.run_id == run_id:
            if _stream_errors:
                raise _stream_errors[0]
            time.sleep(0.5)

        # Stop the WebSocket stream cleanly
        try:
            if not _stream_loop.is_closed():
                future = _asyncio.run_coroutine_threadsafe(
                    thalamus.stop_stream(_is_crypto_first), _stream_loop
                )
                future.result(timeout=5.0)
        except Exception:
            pass
        _stream_thread.join(timeout=10.0)

    except Exception as e:
        crash_exc = e
        crash_traceback = traceback.format_exc(limit=50)
        emit_mner(
            "MNER-F-CORE-101",
            "ENGINE_LOOP_CRASH",
            source="dashboard._engine_loop",
            details={
                "run_id": run_id,
                "mode": current_mode,
                "symbols": symbols,
                "exception_type": e.__class__.__name__,
                "error": _safe_str(e, 500),
            },
        )
        state.push_event("error", {
            "msg": f"Engine crash: {_safe_str(e)}",
            "run_id": run_id,
            "exception_type": e.__class__.__name__,
        })
        print(f"[DASHBOARD] Engine crash: {e}")
        print(crash_traceback)
    finally:
        # Shut down the furnace worker thread before touching state.
        # furnace is a local var captured at engine-start; safe to call without the lock.
        if furnace is not None and hasattr(furnace, "shutdown"):
            try:
                furnace.shutdown()
            except Exception:
                pass

        now_ts = time.time()
        with state.lock:
            stop_requested = state.stop_requested
            stop_source = state.stop_source
            stop_reason = state.stop_reason
            stop_detail = state.stop_detail
            started_at = state.started_at

            if crash_exc is not None:
                exit_kind = "CRASH"
                exit_source = "engine_loop"
                exit_reason = crash_exc.__class__.__name__
                exit_detail = _clip(str(crash_exc), 1000)
                state.last_exception_type = exit_reason
                state.last_exception_msg = exit_detail
                state.last_exception_traceback = _clip(crash_traceback, 12000)
            elif stop_requested:
                exit_kind = "STOP_REQUESTED"
                exit_source = stop_source or "unknown"
                exit_reason = stop_reason or "unspecified"
                exit_detail = stop_detail
            else:
                exit_kind = "UNEXPECTED_STOP"
                exit_source = "internal"
                exit_reason = "running_flag_cleared"
                exit_detail = "Engine loop exited without explicit stop request."

            state.last_run_duration_sec = round(max(now_ts - started_at, 0.0), 3) if started_at else 0.0
            state.last_stopped_at = now_ts
            state.last_exit_at = now_ts
            state.last_exit_kind = exit_kind
            state.last_exit_source = _clip(exit_source, 120)
            state.last_exit_reason = _clip(exit_reason, 200)
            state.last_exit_detail = _clip(exit_detail, 800)

            # Only reset live state if this thread still owns the engine.
            # If a new engine was started before this finally block ran,
            # its run_id will differ — don't clobber it.
            is_current_owner = (state.run_id == run_id)
            if is_current_owner:
                state.running = False
                state.started_at = None
                state._stream_loop = None
                state.active_symbol = None
                state.orchestrator = None
                state.trigger = None
                state.thalamus = None
                state.thread = None
                state.stop_requested = False
                state.stop_requested_at = None
                state.stop_source = ""
                state.stop_reason = ""
                state.stop_detail = ""
                state.run_id = None

        # Only notify clients if this thread still owns the engine.
        # A stale STOPPED event from a superseded thread would incorrectly
        # disable the UI for the new running engine.
        if not is_current_owner:
            _write_engine_lifecycle_event(
                "ENGINE_EXIT",
                run_id=run_id,
                mode=current_mode,
                symbols=symbols,
                exit_kind=exit_kind,
                exit_source=exit_source,
                exit_reason=exit_reason,
                exit_detail=exit_detail,
                duration_sec=state.last_run_duration_sec,
                had_crash=bool(crash_exc),
            )
            print(f"[DASHBOARD] Superseded engine thread exited: run_id={run_id}, exit_kind={exit_kind}")
            return

        state.push_event("engine", {
            "msg": f"Engine stopped ({exit_kind})",
            "lifecycle": "STOPPED",
            "run_id": run_id,
            "exit_kind": exit_kind,
            "exit_source": exit_source,
            "exit_reason": exit_reason,
            "exit_detail": exit_detail,
        })
        _write_engine_lifecycle_event(
            "ENGINE_EXIT",
            run_id=run_id,
            mode=current_mode,
            symbols=symbols,
            exit_kind=exit_kind,
            exit_source=exit_source,
            exit_reason=exit_reason,
            exit_detail=exit_detail,
            duration_sec=state.last_run_duration_sec,
            had_crash=bool(crash_exc),
        )
        print(f"[DASHBOARD] Engine stopped: run_id={run_id}, exit_kind={exit_kind}, reason={exit_reason}")


# ------------------------------------------------------------------ #
#  HARD STOP — kills engine, stream loop, and Fornix atomically        #
# ------------------------------------------------------------------ #
def _kill_thread(t: threading.Thread) -> None:
    """Inject SystemExit into a live thread via ctypes. Kills it on next bytecode."""
    if t is None or not t.is_alive():
        return
    import ctypes
    tid = t.ident
    if tid is None:
        return
    ret = ctypes.pythonapi.PyThreadState_SetAsyncExc(
        ctypes.c_ulong(tid), ctypes.py_object(SystemExit)
    )
    if ret > 1:
        ctypes.pythonapi.PyThreadState_SetAsyncExc(ctypes.c_ulong(tid), None)


def _stop_engine_only(source: str, reason: str, detail: str = "") -> None:
    """Signal the engine thread to stop cleanly. Fornix is unaffected.

    Sets state.running=False so the boundary loop exits within 0.5s, then the
    engine thread's own finally block runs cleanup (stop_stream, furnace.shutdown,
    state reset). Stopping the asyncio loop unblocks the WebSocket stream so the
    stream thread can exit and be joined by the engine thread's cleanup code.
    """
    with state.lock:
        if state.running:
            state.request_stop(source=source, reason=reason, detail=detail)
        loop = state._stream_loop
    if loop is not None and not loop.is_closed():
        try:
            loop.call_soon_threadsafe(loop.stop)
        except Exception:
            pass


def _stop_fornix_only() -> None:
    """Kill the Fornix thread and release duck.db lock. Engine is unaffected."""
    with fornix_state.lock:
        f = fornix_state.fornix
        fornix_thread = fornix_state.thread
    if f is not None:
        f.shutdown_requested = True
        # Close the pond from OUTSIDE the thread first — releases the duck.db file lock
        # immediately regardless of what C extension the thread is currently inside.
        try:
            f.pond.close()
        except Exception:
            pass
    _kill_thread(fornix_thread)
    # Mark state dead now so the next start isn't blocked.
    with fornix_state.lock:
        if fornix_state.thread is fornix_thread:
            fornix_state.running = False
            fornix_state.fornix = None
            fornix_state.thread = None


def _hard_stop(source: str, reason: str, detail: str = "") -> None:
    """Kill both engine and Fornix threads. Docker process stays alive."""
    _stop_engine_only(source=source, reason=reason, detail=detail)
    _stop_fornix_only()


# ------------------------------------------------------------------ #
#  ROUTES: Control                                                     #
# ------------------------------------------------------------------ #
@app.route("/api/start", methods=["POST"])
def api_start():
    try:
        _require_infra()
    except Exception as e:
        return jsonify({"error": "infra_missing", "detail": str(e)}), 503
    data = request.get_json() or {}
    mode = str(data.get("mode", "DRY_RUN")).upper()
    symbols_raw = data.get("symbols", ["BTC/USD"])

    if isinstance(symbols_raw, str):
        symbols_raw = [s.strip() for s in symbols_raw.split(",") if s.strip()]

    symbols = [_normalize_symbol(s) for s in symbols_raw]
    is_crypto_map = {s: _is_crypto_symbol(s) for s in symbols}

    # LIVE mode gate
    if mode == "LIVE":
        if state.kill_switch != "ARMED":
            return jsonify({"error": "live_requires_armed_kill_switch"}), 423
        token = data.get("live_unlock_token")
        if not state.live_unlock_token or token != state.live_unlock_token:
            return jsonify({"error": "invalid_unlock_token"}), 403

    with state.lock:
        if state.running:
            return jsonify({"error": "already_running"}), 409
        run_id = uuid.uuid4().hex
        state.running = True
        state.run_id = run_id
        state.mode = mode
        state.symbols = symbols
        state.bars_processed = 0
        state.started_at = time.time()
        state.last_started_at = state.started_at
        state.last_stopped_at = None
        state.stop_requested = False
        state.stop_requested_at = None
        state.stop_source = ""
        state.stop_reason = ""
        state.stop_detail = ""
        state.last_exception_type = ""
        state.last_exception_msg = ""
        state.last_exception_traceback = ""

    state.thread = threading.Thread(
        target=_engine_loop, args=(symbols, is_crypto_map), daemon=True
    )
    state.thread.start()

    _write_engine_lifecycle_event(
        "ENGINE_START_REQUESTED",
        run_id=run_id,
        mode=mode,
        symbols=symbols,
        source="api_start",
        remote_addr=_clip(request.remote_addr, 80),
    )
    return jsonify({"status": "ok", "mode": mode, "symbols": symbols, "run_id": run_id})


@app.route("/api/stop", methods=["POST"])
def api_stop():
    data = request.get_json(silent=True) or {}
    source = _clip(data.get("source") or request.args.get("source") or "api_stop", 80)
    reason = _clip(data.get("reason") or request.args.get("reason") or "manual_stop", 120)
    detail = _clip(data.get("detail") or request.args.get("detail") or "", 240)
    with state.lock:
        run_id = state.run_id
        was_running = state.running
        if not was_running:
            return jsonify({
                "status": "already_stopped",
                "last_exit_kind": state.last_exit_kind,
                "last_exit_reason": state.last_exit_reason,
            }), 200

    _stop_engine_only(source=source, reason=reason, detail=detail)

    state.push_event("system", {
        "msg": f"Stop requested by {source}: {reason}",
        "source": source,
        "reason": reason,
        "detail": detail,
        "run_id": run_id,
    })
    _write_engine_lifecycle_event(
        "ENGINE_STOP_REQUESTED",
        run_id=run_id,
        source=source,
        reason=reason,
        detail=detail,
        remote_addr=_clip(request.remote_addr, 80),
    )
    return jsonify({"status": "ok", "run_id": run_id, "source": source, "reason": reason})


@app.route("/api/state", methods=["GET"])
def api_state():
    with state.lock:
        uptime = round(time.time() - state.started_at, 1) if (state.running and state.started_at) else 0
        return jsonify({
            "running": state.running,
            "run_id": state.run_id,
            "mode": state.mode,
            "symbols": state.symbols,
            "active_symbol": state.active_symbol,
            "bars_processed": state.bars_processed,
            "started_at": state.started_at,
            "last_started_at": state.last_started_at,
            "last_stopped_at": state.last_stopped_at,
            "last_run_duration_sec": state.last_run_duration_sec,
            "kill_switch": state.kill_switch,
            "trading_enabled": state.trading_enabled,
            "stop_requested": state.stop_requested,
            "stop_source": state.stop_source,
            "stop_reason": state.stop_reason,
            "stop_detail": state.stop_detail,
            "stop_requested_at": state.stop_requested_at,
            "last_exit_kind": state.last_exit_kind,
            "last_exit_source": state.last_exit_source,
            "last_exit_reason": state.last_exit_reason,
            "last_exit_detail": state.last_exit_detail,
            "last_exit_at": state.last_exit_at,
            "last_exception_type": state.last_exception_type,
            "last_exception_msg": state.last_exception_msg,
            "last_exception_traceback": state.last_exception_traceback,
            "uptime_sec": uptime,
        })


@app.route("/api/engine/lifecycle", methods=["GET"])
def api_engine_lifecycle():
    raw_limit = request.args.get("limit", "100")
    try:
        limit = max(1, min(int(raw_limit), 500))
    except Exception:
        limit = 100
    events = _read_engine_lifecycle_tail(limit=limit)
    return jsonify({"status": "ok", "count": len(events), "events": events})


@app.route("/api/mner/tail", methods=["GET"])
def api_mner_tail():
    raw_limit = request.args.get("limit", "100")
    try:
        limit = max(1, min(int(raw_limit), 500))
    except Exception:
        limit = 100
    events = read_mner_tail(limit=limit)
    return jsonify({"status": "ok", "count": len(events), "events": events})


@app.route("/api/furnace/state", methods=["GET"])
def api_furnace_state():
    with state.lock:
        orchestrator = state.orchestrator
    if orchestrator is None or not hasattr(orchestrator, "furnace"):
        return jsonify({"status": "unavailable"}), 503
    try:
        furnace = orchestrator.furnace
        if hasattr(furnace, "get_state"):
            payload = furnace.get_state()
            if not isinstance(payload, dict):
                payload = {}
            tail = payload.get("telemetry_tail", [])
            filtered_tail = []
            if isinstance(tail, list):
                for evt in tail:
                    if not isinstance(evt, dict):
                        continue
                    decision = str(evt.get("decision", "")).upper()
                    if decision in {"EXECUTED", "PIPELINE_ERROR"}:
                        filtered_tail.append(evt)
            payload["telemetry_tail"] = filtered_tail
            if filtered_tail:
                last_evt = filtered_tail[-1]
                payload["last_decision"] = str(last_evt.get("decision", "IDLE")).upper()
                payload["last_activation_logged"] = int(last_evt.get("activation", 0) or 0)
            else:
                payload["last_decision"] = "IDLE"
                payload["last_activation_logged"] = int(payload.get("activation_count", 0) or 0)
            return jsonify({"status": "ok", **payload})
        return jsonify({"status": "unavailable"}), 503
    except Exception as e:
        return jsonify({"status": "error", "detail": _safe_str(e)}), 500


# ------------------------------------------------------------------ #
#  ROUTES: Fornix (Backtest)                                          #
# ------------------------------------------------------------------ #
@app.route("/api/fornix/start", methods=["POST"])
def api_fornix_start():
    data = request.get_json() or {}
    full = bool(data.get("full", False))
    symbols_raw = data.get("symbols", None)

    # Normalise any explicit symbol list
    if isinstance(symbols_raw, str):
        symbols_raw = [s.strip() for s in symbols_raw.split(",") if s.strip()]

    # Auto-pick next stock + crypto combo from DuckDB when caller passes nothing
    if not symbols_raw:
        symbols_raw = _get_next_combo()
        if not symbols_raw:
            return jsonify({"error": "no_symbols_in_market_tape"}), 422

    run_id = _start_fornix_job(full=full, symbols=symbols_raw, source="ui")
    if run_id is None:
        with fornix_state.lock:
            return jsonify({"error": "fornix_already_running", "run_id": fornix_state.run_id}), 409

    return jsonify({"status": "ok", "run_id": run_id, "full": full, "symbols": symbols_raw})


@app.route("/api/fornix/stop", methods=["POST"])
def api_fornix_stop():
    with fornix_state.lock:
        if not fornix_state.running:
            return jsonify({"status": "not_running"}), 200
        run_id = fornix_state.run_id
    _stop_fornix_only()
    state.push_event("fornix_lifecycle", {
        "lifecycle": "STOPPED",
        "run_id": run_id,
        "msg": "Fornix stopped by user",
    })
    return jsonify({"status": "ok", "run_id": run_id})


@app.route("/api/fornix/state", methods=["GET"])
def api_fornix_state():
    with fornix_state.lock:
        uptime = round(time.time() - fornix_state.started_at, 1) if fornix_state.started_at else 0
        pct = 0.0
        if fornix_state.total_bars > 0:
            pct = round(fornix_state.bars_done / fornix_state.total_bars * 100, 1)
        return jsonify({
            "running": fornix_state.running,
            "run_id": fornix_state.run_id,
            "current_symbol": fornix_state.current_symbol,
            "bars_done": fornix_state.bars_done,
            "total_bars": fornix_state.total_bars,
            "pct_complete": pct,
            "mints": fornix_state.mints,
            "signals": fornix_state.signals,
            "bars_per_sec": fornix_state.bars_per_sec,
            "eta_minutes": fornix_state.eta_minutes,
            "last_exit": fornix_state.last_exit,
            "error": fornix_state.error,
            "uptime_sec": uptime,
        })


# ------------------------------------------------------------------ #
#  ROUTES: SSE Stream                                                  #
# ------------------------------------------------------------------ #
@app.route("/api/stream")
def api_stream():
    """Server-Sent Events stream of live BrainFrame pulses."""
    client_q: queue.Queue = queue.Queue(maxsize=200)
    with state.lock:
        state.sse_clients.append(client_q)

    def generate():
        try:
            while True:
                try:
                    event = client_q.get(timeout=5)
                    yield f"data: {json.dumps(event)}\n\n"
                except queue.Empty:
                    yield f": keepalive\n\n"
        finally:
            with state.lock:
                if client_q in state.sse_clients:
                    state.sse_clients.remove(client_q)
                no_clients_left = not state.sse_clients
            # When the last browser client drops, hard-stop everything.
            # This is the reliable path — beforeunload beacons are not guaranteed on hard closes.
            if STOP_ON_WINDOW_CLOSE and no_clients_left:
                _hard_stop(
                    source="sse_disconnect",
                    reason="all_clients_disconnected",
                    detail="All SSE clients dropped — hard stop per STOP_ON_WINDOW_CLOSE policy",
                )

    return Response(
        generate(),
        mimetype="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
            "Connection": "keep-alive",
        },
    )


# ------------------------------------------------------------------ #
#  ROUTES: Treasury                                                    #
# ------------------------------------------------------------------ #
@app.route("/api/treasury/status", methods=["GET"])
def api_treasury_status():
    """Returns Treasury KPIs for the sidebar."""
    try:
        from Medulla.treasury.gland import TreasuryGland
        treasury = TreasuryGland(mode=state.mode)
        status = treasury.get_status()
        orders = status.get("orders", {}) if isinstance(status, dict) else {}
        order_count = int(sum(int(v or 0) for v in orders.values())) if isinstance(orders, dict) else 0
        fill_count = int(orders.get("fired", 0) or 0) if isinstance(orders, dict) else 0
        open_positions = int(status.get("open_positions", 0) or 0) if isinstance(status, dict) else 0
        realized_pnl = float(status.get("realized_pnl", 0.0) or 0.0) if isinstance(status, dict) else 0.0
        unrealized_pnl = float(status.get("unrealized_pnl", 0.0) or 0.0) if isinstance(status, dict) else 0.0
        daily_realized = float(treasury.get_realized_pnl_for_day())
        daily_loss = min(daily_realized, 0.0)
        payload = {
            "mode": status.get("mode", state.mode) if isinstance(status, dict) else state.mode,
            "order_count": order_count,
            "fill_count": fill_count,
            "open_positions": open_positions,
            "realized_pnl": realized_pnl,
            "unrealized_pnl": unrealized_pnl,
            "daily_loss": daily_loss,
            # Backward-compat keys
            "orders": order_count,
            "fills": fill_count,
            "positions": open_positions,
            "net_pnl": realized_pnl + unrealized_pnl,
            "drawdown": abs(daily_loss),
            "win_rate": 0.0,
        }
        return jsonify(payload)
    except Exception as e:
        return jsonify({
            "order_count": 0, "fill_count": 0, "open_positions": 0,
            "realized_pnl": 0.0, "unrealized_pnl": 0.0, "daily_loss": 0.0,
            "orders": 0, "fills": 0, "positions": 0, "net_pnl": 0.0, "drawdown": 0.0, "win_rate": 0.0,
            "error": _safe_str(e, 100),
        })


# ------------------------------------------------------------------ #
#  ROUTES: Vault / Gold Params                                         #
# ------------------------------------------------------------------ #
@app.route("/api/vault/gold", methods=["GET"])
def api_vault_gold():
    """Returns the current Gold parameter set from the hormonal vault."""
    gold = {}
    try:
        from Hippocampus.Archivist.librarian import librarian
        vault = librarian.get_hormonal_vault()
        gold = vault.get("gold", {})
    except Exception:
        pass

    # Piece 21: Enrich with environment execution defaults
    params = gold.get("params", {}).copy()
    if "fee_maker_bps" not in params:
        params["fee_maker_bps"] = float(os.getenv("MAMMON_FEE_MAKER_BPS", 2.0))
    if "fee_taker_bps" not in params:
        params["fee_taker_bps"] = float(os.getenv("MAMMON_FEE_TAKER_BPS", 4.0))
    if "max_slippage_bps" not in params:
        params["max_slippage_bps"] = float(os.getenv("MAMMON_MAX_SLIPPAGE_BPS", 5.0))
    if "risk_per_trade_pct" not in params:
        params["risk_per_trade_pct"] = float(os.getenv("MAMMON_RISK_PER_TRADE_PCT", 0.01))
    if "equity" not in params:
        params["equity"] = float(os.getenv("MAMMON_INITIAL_EQUITY", 10000.0))

    return jsonify({
        "id": gold.get("id", "UNKNOWN"),
        "params": params,
        "fitness_snapshot": gold.get("fitness_snapshot", 0.0),
        "coronated_at": gold.get("coronated_at", ""),
        "origin": gold.get("origin", ""),
    })


# ------------------------------------------------------------------ #
#  ROUTES: Risk / Kill Switch                                          #
# ------------------------------------------------------------------ #
@app.route("/api/risk/kill-switch", methods=["POST"])
def api_kill_switch():
    data = request.get_json() or {}
    action = str(data.get("action", "")).lower()

    if action == "trip":
        with state.lock:
            state.kill_switch = "TRIPPED"
            state.mode = "LOCKED"
            state.trading_enabled = False
        if state.orchestrator and hasattr(state.orchestrator, "set_execution_mode"):
            state.orchestrator.set_execution_mode("LOCKED")
        if state.trigger and hasattr(state.trigger, "set_execution_mode"):
            state.trigger.set_execution_mode("LOCKED")
        state.push_event("system", {"msg": "KILL SWITCH TRIPPED", "mode": "LOCKED"})
        return jsonify({"status": "ok", "kill_switch": "TRIPPED", "mode": "LOCKED"})

    if action == "reset":
        with state.lock:
            state.kill_switch = "ARMED"
            state.mode = "DRY_RUN"
            state.trading_enabled = True
        if state.orchestrator and hasattr(state.orchestrator, "set_execution_mode"):
            state.orchestrator.set_execution_mode("DRY_RUN")
        if state.trigger and hasattr(state.trigger, "set_execution_mode"):
            state.trigger.set_execution_mode("DRY_RUN")
        state.push_event("system", {"msg": "Kill switch reset", "mode": "DRY_RUN"})
        return jsonify({"status": "ok", "kill_switch": "ARMED", "mode": "DRY_RUN"})

    return jsonify({"error": "invalid_action"}), 400


@app.route("/api/mode/live-unlock/arm", methods=["POST"])
def api_live_unlock_arm():
    state.live_unlock_token = str(uuid.uuid4())
    return jsonify({"status": "ok", "token": state.live_unlock_token})


# ------------------------------------------------------------------ #
#  ROUTES: Latest Frame (poll fallback)                                #
# ------------------------------------------------------------------ #
@app.route("/api/frame/latest", methods=["GET"])
def api_frame_latest():
    """Returns the last BrainFrame snapshot (for polling fallback)."""
    with state.lock:
        if state.last_frame_dict:
            return jsonify(state.last_frame_dict)
    return jsonify({"status": "no_data"})


# ------------------------------------------------------------------ #
#  ROUTES: Static Dashboard                                            #
# ------------------------------------------------------------------ #
@app.route("/")
def serve_index():
    """Serve the dashboard UI with token injected."""
    html_path = DASHBOARD_DIR / "index.html"
    html_content = html_path.read_text(encoding="utf-8")
    # Inject token so the UI never needs manual entry
    stop_on_close_js = "true" if STOP_ON_WINDOW_CLOSE else "false"
    injected = html_content.replace(
        "</head>",
        (
            f'<script>window.MAMMON_TOKEN="{API_BEARER_TOKEN}";'
            f"window.MAMMON_STOP_ON_CLOSE={stop_on_close_js};</script>\n</head>"
        ),
    )
    return injected, 200, {
        "Content-Type": "text/html; charset=utf-8",
        "Cache-Control": "no-store, no-cache, must-revalidate, max-age=0",
        "Pragma": "no-cache",
        "Expires": "0",
    }


@app.route("/<path:path>")
def serve_static(path):
    """Catch-all: serve files from the dashboard/ directory."""
    file_path = DASHBOARD_DIR / path
    if file_path.is_file():
        resp = send_from_directory(str(DASHBOARD_DIR), path)
    else:
        # Fallback to index.html for SPA-style routing
        resp = send_from_directory(str(DASHBOARD_DIR), "index.html")

    resp.headers["Cache-Control"] = "no-store, no-cache, must-revalidate, max-age=0"
    resp.headers["Pragma"] = "no-cache"
    resp.headers["Expires"] = "0"
    return resp


# ------------------------------------------------------------------ #
#  MAIN                                                                #
# ------------------------------------------------------------------ #
def main():
    port = int(os.environ.get("MAMMON_DASHBOARD_PORT", 5000))
    print(f"[DASHBOARD] Starting Mammon Dashboard API on port {port}")
    print(f"[DASHBOARD] Serving UI from: {DASHBOARD_DIR}")
    print(f"[DASHBOARD] API Token: {API_BEARER_TOKEN[:4]}...")
    _require_infra()

    # Start midnight Fornix scheduler (fires at 00:00 UTC; skips if engine not live)
    try:
        from apscheduler.schedulers.background import BackgroundScheduler
        from apscheduler.triggers.cron import CronTrigger
        _sched = BackgroundScheduler(daemon=True, timezone="UTC")
        _sched.add_job(
            _midnight_fornix_job,
            CronTrigger(hour=0, minute=0, timezone="UTC"),
            id="midnight_fornix",
            replace_existing=True,
        )
        _sched.start()
        print("[DASHBOARD] Midnight Fornix scheduler armed (00:00 UTC — only fires when engine is live)")
    except ImportError:
        print("[DASHBOARD] APScheduler not found — midnight Fornix disabled. Run: pip install apscheduler")
    except Exception as e:
        print(f"[DASHBOARD] Scheduler start failed: {e}")

    app.run(host="0.0.0.0", port=port, debug=False, threaded=True)


if __name__ == "__main__":
    main()
