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
import uuid
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

load_dotenv()

# ------------------------------------------------------------------ #
#  APP & AUTH                                                          #
# ------------------------------------------------------------------ #
DASHBOARD_DIR = ROOT_DIR / "dashboard"
app = Flask(__name__, static_folder=str(DASHBOARD_DIR), static_url_path="/static")
API_BEARER_TOKEN = os.environ.get("MAMMON_API_TOKEN", "dev-token")
_rate_buckets: Dict[str, list] = {}

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
        self.started_at: Optional[float] = None
        self.lock = threading.Lock()

        # SSE queues
        self.sse_queue: queue.Queue = queue.Queue(maxsize=500)

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

    def push_event(self, event_type: str, data: dict):
        """Push event to SSE listeners. Non-blocking."""
        event = {
            "type": event_type,
            "data": data,
            "ts": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        }
        try:
            self.sse_queue.put_nowait(event)
        except queue.Full:
            # Drop oldest to make room
            try:
                self.sse_queue.get_nowait()
                self.sse_queue.put_nowait(event)
            except queue.Empty:
                pass


state = EngineState()


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

        # Initialize Async persistence (Scribe Daemon)
        _telepathy = Telepathy()

        with state.lock:
            current_mode = state.mode
            trading_enabled = state.trading_enabled

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

        state.push_event("engine", {"msg": f"Engine started in mode={current_mode}"})
        print(f"[DASHBOARD] Engine started: mode={current_mode}, symbols={symbols}")

        # ── Wait for the nearest 5-minute boundary ──
        import math
        now_ts = time.time()
        target = math.ceil(now_ts / 300) * 300 
        wait_sec = max(target - time.time(), 0)
        
        state.push_event("system", {
            "msg": f"Syncing to 5m boundary — waiting {wait_sec:.0f}s",
        })
        print(f"[DASHBOARD] Waiting {wait_sec:.0f}s for next 5m boundary")
        
        while wait_sec > 0 and state.running:
            time.sleep(min(1.0, wait_sec))
            wait_sec = max(target - time.time(), 0)
            
        if not state.running:
            return
            
        state.push_event("system", {"msg": "Boundary reached — pipeline live"})
        print("[DASHBOARD] Boundary reached — starting poll loop")

        # Poll loop
        poll_interval_sec = 0.5
        last_seen_bar_ts: Dict[str, Any] = {}
        last_wallclock_window_start: Optional[int] = None
        last_wallclock_mint_window_start: Optional[int] = None

        # Initialize wall-clock window tracking to force a MINT on the first boundary
        current_window_start = int(time.time() // 300) * 300
        last_wallclock_window_start = current_window_start - 300

        while state.running:
            for symbol in symbols:
                if not state.running:
                    break

                with state.lock:
                    state.active_symbol = symbol
                    loop_mode = state.mode

                is_crypto = is_crypto_map.get(symbol, True)

                try:
                    # Piece 14: Wall-clock MINT trigger
                    now_ts = time.time()
                    current_window_start = int(now_ts // 300) * 300
                    if last_wallclock_window_start is not None and current_window_start > last_wallclock_window_start:
                        mint_window_start = current_window_start - 300
                        frame = orchestrator.frame
                        event_data = _frame_to_event(frame, symbol, "MINT", loop_mode)
                        state.push_event("pulse", event_data)
                        last_wallclock_window_start = current_window_start
                        last_wallclock_mint_window_start = mint_window_start
                        print(f"[DASHBOARD] Wall-clock MINT triggered for {symbol} (Window: {mint_window_start})")

                    latest = thalamus.get_latest_bar(symbol=symbol, is_crypto=is_crypto)
                    raw_df, bar_ts = _bar_to_dict(latest, symbol)
                    if raw_df is None or bar_ts is None:
                        continue
                    
                    # Update window tracker from bar data
                    this_bar_window = (int(bar_ts.timestamp()) // 300) * 300

                    prev = last_seen_bar_ts.get(symbol)
                    if prev is not None and bar_ts <= prev:
                        continue

                    last_seen_bar_ts[symbol] = bar_ts
                    pulses = thalamus.drip_pulse(raw_df)

                    with state.lock:
                        state.bars_processed += 1

                    if pulses:
                        frame = orchestrator.frame
                        pulse_type = pulses[-1][0] if isinstance(pulses[-1], (list, tuple)) else str(getattr(pulses[-1], "pulse_type", "MINT"))
                        event_data = _frame_to_event(
                            frame, symbol, pulse_type, loop_mode,
                            bar_dict={
                                "bar_time": int(bar_ts.timestamp()),
                                "bar_open": round(float(raw_df.iloc[0]["open"]), 4),
                                "bar_high": round(float(raw_df.iloc[0]["high"]), 4),
                                "bar_low": round(float(raw_df.iloc[0]["low"]), 4),
                                "bar_close": round(float(raw_df.iloc[0]["close"]), 4),
                                "bar_volume": round(float(raw_df.iloc[0]["volume"]), 2),
                            },
                        )

                        with state.lock:
                            state.last_frame_dict = event_data

                        if pulse_type == "MINT":
                            minted_window_start = this_bar_window - 300
                            if last_wallclock_mint_window_start is not None and minted_window_start == last_wallclock_mint_window_start:
                                continue
                        state.push_event("pulse", event_data)

                except Exception as e:
                    state.push_event("error", {"symbol": symbol, "msg": _safe_str(e)})

            time.sleep(poll_interval_sec)

    except Exception as e:
        state.push_event("error", {"msg": f"Engine crash: {_safe_str(e)}"})
        print(f"[DASHBOARD] Engine crash: {e}")
        import traceback
        traceback.print_exc()
    finally:
        state.push_event("engine", {"msg": "Engine stopped"})
        with state.lock:
            state.running = False
            state.orchestrator = None
            state.trigger = None
            state.thalamus = None
            state.thread = None
        print("[DASHBOARD] Engine stopped.")


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
        state.running = True
        state.mode = mode
        state.symbols = symbols
        state.bars_processed = 0
        state.started_at = time.time()

    state.thread = threading.Thread(
        target=_engine_loop, args=(symbols, is_crypto_map), daemon=True
    )
    state.thread.start()

    return jsonify({"status": "ok", "mode": mode, "symbols": symbols})


@app.route("/api/stop", methods=["POST"])
def api_stop():
    with state.lock:
        state.running = False
    return jsonify({"status": "ok"})


@app.route("/api/state", methods=["GET"])
def api_state():
    with state.lock:
        return jsonify({
            "running": state.running,
            "mode": state.mode,
            "symbols": state.symbols,
            "active_symbol": state.active_symbol,
            "bars_processed": state.bars_processed,
            "started_at": state.started_at,
            "kill_switch": state.kill_switch,
            "trading_enabled": state.trading_enabled,
            "uptime_sec": round(time.time() - state.started_at, 1) if state.started_at else 0,
        })


# ------------------------------------------------------------------ #
#  ROUTES: SSE Stream                                                  #
# ------------------------------------------------------------------ #
@app.route("/api/stream")
def api_stream():
    """Server-Sent Events stream of live BrainFrame pulses."""
    def generate():
        while True:
            try:
                event = state.sse_queue.get(timeout=30)
                yield f"data: {json.dumps(event)}\n\n"
            except queue.Empty:
                # Send keepalive
                yield f": keepalive\n\n"

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
        return jsonify(status)
    except Exception as e:
        return jsonify({
            "orders": 0, "fills": 0, "positions": 0,
            "net_pnl": 0.0, "drawdown": 0.0, "win_rate": 0.0,
            "error": _safe_str(e, 100),
        })


# ------------------------------------------------------------------ #
#  ROUTES: Vault / Gold Params                                         #
# ------------------------------------------------------------------ #
@app.route("/api/vault/gold", methods=["GET"])
def api_vault_gold():
    """Returns the current Gold parameter set from the hormonal vault."""
    gold = {}
    # Primary: try through the librarian (uses Redis if available)
    try:
        from Hippocampus.Archivist.librarian import librarian
        vault = librarian.get_hormonal_vault()
        gold = vault.get("gold", {})
    except Exception:
        pass

    return jsonify({
        "id": gold.get("id", "UNKNOWN"),
        "params": gold.get("params", {}),
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
    injected = html_content.replace(
        "</head>",
        f'<script>window.MAMMON_TOKEN="{API_BEARER_TOKEN}";</script>\n</head>',
    )
    return injected, 200, {"Content-Type": "text/html; charset=utf-8"}


@app.route("/<path:path>")
def serve_static(path):
    """Catch-all: serve files from the dashboard/ directory."""
    file_path = DASHBOARD_DIR / path
    if file_path.is_file():
        return send_from_directory(str(DASHBOARD_DIR), path)
    # Fallback to index.html for SPA-style routing
    return send_from_directory(str(DASHBOARD_DIR), "index.html")


# ------------------------------------------------------------------ #
#  MAIN                                                                #
# ------------------------------------------------------------------ #
def main():
    port = int(os.environ.get("MAMMON_DASHBOARD_PORT", 5000))
    print(f"[DASHBOARD] Starting Mammon Dashboard API on port {port}")
    print(f"[DASHBOARD] Serving UI from: {DASHBOARD_DIR}")
    print(f"[DASHBOARD] API Token: {API_BEARER_TOKEN[:4]}...")
    _require_infra()
    app.run(host="0.0.0.0", port=port, debug=False, threaded=True)


if __name__ == "__main__":
    main()
