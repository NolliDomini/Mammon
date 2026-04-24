import numpy as np
import time
import threading
import uuid
import math
from datetime import datetime, timezone
from typing import Dict, Any, Optional
from alpaca.trading.client import TradingClient
from alpaca.trading.requests import MarketOrderRequest
from alpaca.trading.enums import OrderSide, TimeInForce
from Cerebellum.Soul.brain_frame import BrainFrame


class Trigger:
    """
    Brain Stem: The Trigger Train (V3.3 Gated Architecture).
    
    GATES (Must be OPEN):
      1. Risk Gate (Small Monte): Score >= configured floor (Safe)
      2. Valuation Cap (StdDev): Entry z-score <= configured cap
      
    TRIGGER (Must FIRE):
      3. Engine Conviction: Prior > 0.5 (Turtle + Council)
      
    LONG ONLY:
      BUY  = Risk >= MinRisk  AND  EntryZ <= EntryCap  AND  Prior > 0.5
      SELL = (Price > Mean AND Diverging)  OR  Hard Bands (Stop/Take)
    """

    def __init__(self, api_key, api_secret, paper=True, config: Dict[str, Any] = None):
        self.config = config or {}
        self.api_key = api_key
        self.api_secret = api_secret
        self.execution_mode = str(self.config.get("execution_mode", "DRY_RUN")).upper()
        self.client = None
        self.execution_adapter = "mock"
        self._adapter_lock = threading.Lock()
        if self.execution_mode not in ["DRY_RUN", "BACKTEST"]:
            self.client = TradingClient(api_key, api_secret, paper=paper)
            self.execution_adapter = "alpaca"
        self.rng = np.random.default_rng()
        self.treasury = None
        try:
            from Medulla.treasury.gland import TreasuryGland
            self.treasury = TreasuryGland(mode=self.execution_mode)
        except Exception as e:
            print(f"[BRAIN STEM] Treasury unavailable: {e}")
            self.treasury = None

        # State
        self.risk_score = 0.0          # Gate 1
        self.last_trigger_score = 0.0  # Compat
        self.prev_price = None         # Momentum
        self.position = None           # Active trade
        self.last_exit_reason = None   # Telemetry
        self.pending_entry = None      # ACTION->MINT deferred execution
        self.mean_dev_monitor_active = False
        self.last_execution_event = {}

        # Recover open position state from treasury on restart to keep mark_to_market alive
        if self.treasury is not None:
            try:
                open_pos = self.treasury.get_open_positions()
                if open_pos:
                    p = open_pos[0]
                    self.position = {
                        "symbol": p["symbol"],
                        "entry_price": float(p["avg_price"]),
                        "qty": float(p["qty"]),
                        "bands": {},
                        "entry_z": float(p["z_score"] or 0.0),
                        "mean_at_entry": float(p["mean"] or p["avg_price"]),
                        "sigma_at_entry": float(p["sigma"] or 1e-9),
                    }
                    print(f"[BRAIN STEM] Recovered open position: {p['symbol']} qty={p['qty']} @ {p['avg_price']}")
            except Exception as e:
                print(f"[BRAIN STEM] Position recovery failed: {e}")

    def set_execution_mode(self, mode: str):
        mode_u = str(mode or "DRY_RUN").upper()
        paper = mode_u == "PAPER"
        with self._adapter_lock:
            self.execution_mode = mode_u
            self.config["execution_mode"] = mode_u
            self.execution_adapter = "mock"
            self.client = None
            if mode_u not in ["DRY_RUN", "BACKTEST"]:
                try:
                    self.client = TradingClient(self.api_key, self.api_secret, paper=paper)
                    self.execution_adapter = "alpaca"
                except Exception as e:
                    print(f"[BRAIN STEM] Adapter rebind failed for {mode_u}: {e}")
                    self.execution_adapter = "mock"
                    self.client = None
            try:
                from Medulla.treasury.gland import TreasuryGland
                self.treasury = TreasuryGland(mode=mode_u)
            except Exception as e:
                print(f"[BRAIN STEM] Treasury rebind failed for {mode_u}: {e}")
                self.treasury = None

    def _get_prior(self, frame: BrainFrame) -> float:
        """Calculate the blended conviction score (Prior)."""
        w_turtle = float(self.config.get("brain_stem_w_turtle", 0.5))
        w_council = float(self.config.get("brain_stem_w_council", 0.5))
        return (frame.risk.monte_score * w_turtle) + (frame.environment.confidence * w_council)

    def _trading_enabled(self, orchestrator=None) -> bool:
        if orchestrator is None:
            return True
        cfg = getattr(orchestrator, "config", {}) or {}
        trade_gate = cfg.get("trading_enabled_provider")
        if callable(trade_gate):
            try:
                return bool(trade_gate())
            except Exception:
                return False
        return True

    def _is_valid_mode(self) -> bool:
        return str(self.execution_mode or "").upper() in {"DRY_RUN", "PAPER", "LIVE", "BACKTEST"}

    def _valid_execution_payload(self, frame: BrainFrame) -> tuple[bool, str, float, float]:
        symbol = str(getattr(getattr(frame, "market", None), "symbol", "") or "").strip()
        qty = getattr(getattr(frame, "command", None), "sizing_mult", 0.0)
        price = getattr(getattr(frame, "structure", None), "price", 0.0)
        try:
            qty_f = float(qty)
            price_f = float(price)
        except Exception:
            return False, symbol or "UNKNOWN", 0.0, 0.0
        if (not symbol) or (qty_f <= 0.0) or (not math.isfinite(price_f)) or (price_f <= 0.0):
            return False, symbol or "UNKNOWN", max(0.0, qty_f), max(0.0, price_f)
        return True, symbol, qty_f, price_f

    def _emit_exec_event(self, pulse_type: str, transition: str, reason: str, **extra):
        self.last_execution_event = {
            "ts": datetime.now(timezone.utc).isoformat(),
            "pulse_type": str(pulse_type).upper(),
            "mode": str(self.execution_mode).upper(),
            "adapter": str(self.execution_adapter),
            "transition": transition,
            "reason": reason,
            **extra,
        }

    # ------------------------------------------------------------------ #
    #  GATE 1: RISK (Small Monte)                                        #
    # ------------------------------------------------------------------ #
    def _run_risk_gate(self, frame: BrainFrame, prior: float) -> float:
        """
        Small Monte (1k paths). Returns risk_score.
        PASS Condition: risk_score > 0.5
        """
        paths_per_lane = int(self.config.get("risk_gate_paths_per_lane", 333))
        total_paths = paths_per_lane * 3
        
        sigma_mult = float(self.config.get("brain_stem_sigma", 0.10))
        bias_scalar = float(self.config.get("brain_stem_bias", 0.05)) # Default small positive bias
        
        noise = self.rng.normal(0, frame.environment.atr * sigma_mult, total_paths)
        
        # Inject Bias based on Prior (Conviction)
        bias = (prior - 0.5) * (frame.environment.atr * bias_scalar)
        
        final_prices = frame.structure.price + noise + bias
        hits = final_prices > frame.structure.price
        rates = np.mean(hits.reshape(3, paths_per_lane), axis=1)
        
        w_worst = float(self.config.get("monte_w_worst", 0.20))
        w_neutral = float(self.config.get("monte_w_neutral", 0.35))
        w_best = float(self.config.get("monte_w_best", 0.45))
        w_sum = w_worst + w_neutral + w_best + 1e-9
        
        self.risk_score = float(
            (rates[0] * w_worst + rates[1] * w_neutral + rates[2] * w_best) / w_sum
        )
        return self.risk_score

    # ------------------------------------------------------------------ #
    #  GATE 2: VALUATION (StdDev Monte)                                  #
    # ------------------------------------------------------------------ #
    def _run_valuation_gate(self, frame: BrainFrame, prior: float, walk_seed=None) -> Dict[str, float]:
        """
        StdDev Monte (10k paths). Calculates bands and Fair Value (Mean).
        PASS Condition (Long): Price < Mean
        """
        paths = int(self.config.get("valuation_paths", 10000))
        sigma_mult = float(self.config.get("brain_stem_sigma", 0.10))
        bias_scalar = float(self.config.get("brain_stem_bias", 0.05))

        mu = (walk_seed.mu * 0.1) if walk_seed else 0.0
        
        # Inject Bias based on Prior
        bias = (prior - 0.5) * (frame.environment.atr * bias_scalar)
        noise = self.rng.normal(mu, frame.environment.atr * sigma_mult, paths)

        final_prices = frame.structure.price + noise + bias
        mean_price = float(np.mean(final_prices))
        sigma = float(np.std(final_prices))

        upper = mean_price + 2.0 * sigma
        lower = mean_price - 1.5 * sigma
        
        return {
            "mean": mean_price,
            "sigma": sigma,
            "upper": upper,
            "lower": lower
        }

    # ------------------------------------------------------------------ #
    #  THE HUNT                                                          #
    # ------------------------------------------------------------------ #
    def load_and_hunt(self, pulse_type: str, frame: BrainFrame,
                      orchestrator=None, walk_engine=None, walk_seed=None, timeout_sec=None):
        pulse = str(pulse_type or "").upper()
        if pulse not in {"ACTION", "MINT"}:
            self.prev_price = getattr(getattr(frame, "structure", None), "price", None)
            return True

        if not self._is_valid_mode():
            self.last_exit_reason = f"MODE_GATE_CANCEL (invalid mode={self.execution_mode})"
            self._emit_exec_event(pulse, "MODE_GATE", self.last_exit_reason)
            self.prev_price = getattr(getattr(frame, "structure", None), "price", None)
            return True

        # MINT finalizes pending ACTION approvals.
        if pulse == "MINT":
            if self.pending_entry is not None and self.position is None:
                intent_id = self.pending_entry.get("intent_id")
                symbol = self.pending_entry["symbol"]
                qty = self.pending_entry["qty"]
                price = frame.structure.price
                if not self._trading_enabled(orchestrator):
                    self.last_exit_reason = "MODE_GATE_CANCEL (trading disabled at MINT)"
                    if self.treasury and intent_id:
                        self.treasury.cancel_intent(intent_id, symbol, self.last_exit_reason)
                    self._emit_exec_event(pulse, "CANCEL", self.last_exit_reason, symbol=symbol, intent_id=intent_id)
                    self.pending_entry = None
                    self.mean_dev_monitor_active = False
                    self.prev_price = frame.structure.price
                    return True

                stale_guard_bps = float(self.config.get("brain_stem_stale_price_cancel_bps", 0.0))
                armed_price = float(self.pending_entry.get("armed_price", price))
                stale_bps = 0.0
                if armed_price > 0:
                    stale_bps = abs(price - armed_price) / armed_price * 10000.0
                if stale_guard_bps > 0.0 and stale_bps >= stale_guard_bps:
                    self.last_exit_reason = (
                        f"STALE_PRICE_CANCEL ({stale_bps:.1f}bps >= {stale_guard_bps:.1f}bps)"
                    )
                    if self.treasury and intent_id:
                        self.treasury.cancel_intent(intent_id, symbol, self.last_exit_reason)
                    self._emit_exec_event(
                        pulse,
                        "CANCEL",
                        self.last_exit_reason,
                        symbol=symbol,
                        intent_id=intent_id,
                        stale_bps=stale_bps,
                    )
                    self.pending_entry = None
                    self.mean_dev_monitor_active = False
                    self.prev_price = frame.structure.price
                    return True

                prior = self._get_prior(frame)
                # Mean reversion kill-switch between ACTION arming and MINT firing.
                mean_ref = self.pending_entry.get("mean_at_entry", price)
                sigma_ref = max(self.pending_entry.get("sigma_at_entry", 1e-9), 1e-9)
                z_score = (frame.structure.price - mean_ref) / sigma_ref
                cancel_sigma = float(self.config.get("brain_stem_mean_dev_cancel_sigma", 0.0))

                if cancel_sigma > 0.0 and z_score >= cancel_sigma:
                    self.last_exit_reason = f"MEAN_DEV_CANCEL (z={z_score:.2f} >= {cancel_sigma:.2f})"
                    if self.treasury and intent_id:
                        self.treasury.cancel_intent(intent_id, symbol, self.last_exit_reason)
                    self._emit_exec_event(
                        pulse,
                        "CANCEL",
                        self.last_exit_reason,
                        symbol=symbol,
                        intent_id=intent_id,
                    )
                else:
                    # Execute fire logic
                    val_data = self._run_valuation_gate(frame, prior, walk_seed)
                    print(
                        f"   [BRAIN STEM] MINT FIRE {symbol} @ {price:.4f}"
                    )
                    fire_result = self._fire_physical(symbol, "BUY", qty, price)
                    if not isinstance(fire_result, dict):
                        fire_result = {"status": "fired", "source": "compat"}
                    if fire_result.get("status") != "fired":
                        self.last_exit_reason = f"REJECT_ADAPTER_FAILURE ({fire_result.get('msg', 'unknown')})"
                        if self.treasury and intent_id:
                            self.treasury.reject_intent(intent_id, symbol, self.last_exit_reason)
                        self._emit_exec_event(
                            pulse,
                            "REJECT",
                            self.last_exit_reason,
                            symbol=symbol,
                            intent_id=intent_id,
                            adapter=self.execution_adapter,
                        )
                    else:
                        if self.treasury and intent_id:
                            self.treasury.fire_intent(
                                intent_id,
                                symbol,
                                "BUY",
                                qty,
                                price,
                                sigma=float(val_data.get("sigma", 0.0)),
                                price_ref=float(self.pending_entry.get("armed_price", price)),
                            )
                        self.position = {
                            "side": "LONG",
                            "entry_price": price,
                            "entry_ts": time.time(),
                            "qty": qty,
                            "bands": self.pending_entry.get("bands", {}),
                            "symbol": symbol,
                            "entry_z": self.pending_entry.get("entry_z", 0.0),
                            "mean_at_entry": self.pending_entry.get("mean_at_entry", price),
                            "sigma_at_entry": self.pending_entry.get("sigma_at_entry", 1e-9),
                        }
                        self._emit_exec_event(
                            pulse,
                            "FIRE",
                            "MINT_FIRED",
                            symbol=symbol,
                            intent_id=intent_id,
                            qty=qty,
                            price=price,
                        )
            self.pending_entry = None
            self.mean_dev_monitor_active = False
            self.prev_price = frame.structure.price
            return True

        # Brain Stem execution logic is keyed off ACTION pulse for pre-fire checks.
        # Enforce policy ownership: Brain Stem cannot independently approve.
        if not bool(getattr(frame.command, "ready_to_fire", True)) or int(getattr(frame.command, "approved", 1) or 0) != 1:
            self.last_exit_reason = "REJECT_POLICY_NOT_FIRE_ELIGIBLE"
            self._emit_exec_event(pulse, "REJECT", self.last_exit_reason)
            self.prev_price = frame.structure.price
            return True

        if not self._trading_enabled(orchestrator):
            self.last_exit_reason = "MODE_GATE_CANCEL (trading disabled at ACTION)"
            self._emit_exec_event(pulse, "CANCEL", self.last_exit_reason)
            self.prev_price = frame.structure.price
            return True

        valid_payload, symbol, qty, price = self._valid_execution_payload(frame)
        if not valid_payload:
            self.last_exit_reason = "REJECT_INVALID_PAYLOAD"
            intent_id = f"{symbol}:{int(time.time() * 1000)}:{uuid.uuid4().hex[:8]}"
            if self.treasury is not None:
                # Invalid payloads still get a terminal ledger row for auditability.
                ts_now = time.time()
                safe_symbol = symbol or "UNKNOWN"
                self.treasury.librarian.write_only(
                    """
                    INSERT OR REPLACE INTO money_orders(
                        intent_id, ts, symbol, side, qty, trigger_pulse, mode, status,
                        price_ref, mean, sigma, z_score, risk_score, confidence, reason, updated_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        intent_id,
                        ts_now,
                        safe_symbol,
                        "BUY",
                        max(0.0, float(qty or 0.0)),
                        "ACTION",
                        self.execution_mode,
                        "REJECTED",
                        max(0.0, float(price or 0.0)),
                        0.0,
                        0.0,
                        0.0,
                        0.0,
                        0.0,
                        self.last_exit_reason,
                        ts_now,
                    ),
                )
                self.treasury._audit(
                    "REJECTED",
                    intent_id,
                    safe_symbol,
                    {"reason": self.last_exit_reason, "mode": self.execution_mode, "ts": ts_now},
                )
            self._emit_exec_event(pulse, "REJECT", self.last_exit_reason, symbol=symbol, intent_id=intent_id)
            self.prev_price = frame.structure.price
            return True

        # 0. Calculate Prior (Trigger/Conviction)
        prior = self._get_prior(frame)
        if self.treasury is None:
            self.last_exit_reason = "REJECT_TREASURY_UNAVAILABLE"
            print("   [BRAIN STEM] WAIT: Treasury unavailable -> NO_ACTION")
            self._emit_exec_event(pulse, "REJECT", self.last_exit_reason, symbol=symbol)
            self.prev_price = frame.structure.price
            return True
        
        # 1. GATE 1: RISK
        risk = self._run_risk_gate(frame, prior)
        
        # 2. GATE 2: VALUATION (Using shared walk_seed)
        val_data = self._run_valuation_gate(frame, prior, walk_seed)
        bands = val_data
        self.last_trigger_score = risk  # Telemetry

        # Piece 21 Bridge: Write results back to BrainFrame for UI/DB visibility
        frame.risk.monte_score = float(risk)
        frame.valuation.mean = float(val_data["mean"])
        frame.valuation.sigma = float(val_data["sigma"])
        frame.valuation.upper_band = float(val_data["upper"])
        frame.valuation.lower_band = float(val_data["lower"])
        frame.valuation.z_distance = float((price - val_data["mean"]) / max(val_data["sigma"], 1e-9))
        
        # ---- LOGIC ----
        if self.position is None:
            # ENTRY LOGIC
            min_risk = float(self.config.get("gatekeeper_min_monte", 0.5))
            is_safe = risk >= min_risk
            sigma = max(val_data.get("sigma", 0.0), 1e-9)
            entry_z = (price - val_data["mean"]) / sigma
            entry_max_z = float(self.config.get("brain_stem_entry_max_z", 0.8))
            is_entry_within_z_cap = entry_z <= entry_max_z
            
            # V3.3: Council is a fail-safe only (Environmental Confidence)
            min_council = float(self.config.get("gatekeeper_min_council", 0.5))
            is_environment_safe = frame.environment.confidence >= min_council
            is_conviction = prior > 0.5
            cap_reason = None

            max_notional = float(self.config.get("max_notional_per_order", 0.0) or 0.0)
            qty = float(frame.command.sizing_mult or 0.0)
            notional = qty * float(price)
            if max_notional > 0.0 and notional > max_notional:
                cap_reason = f"RISK_CAP_MAX_NOTIONAL ({notional:.2f}>{max_notional:.2f})"

            if cap_reason is None and self.treasury is not None:
                max_open_positions = int(self.config.get("max_open_positions", 0) or 0)
                if max_open_positions > 0:
                    open_positions = int(self.treasury.get_open_positions_count())
                    if open_positions >= max_open_positions:
                        cap_reason = f"RISK_CAP_MAX_OPEN_POSITIONS ({open_positions}>={max_open_positions})"

            if cap_reason is None and self.treasury is not None:
                max_daily_realized_loss = float(self.config.get("max_daily_realized_loss", 0.0) or 0.0)
                if max_daily_realized_loss > 0.0:
                    today_net = float(self.treasury.get_realized_pnl_for_day())
                    # Loss is represented by negative net pnl.
                    if today_net <= -abs(max_daily_realized_loss):
                        cap_reason = (
                            f"RISK_CAP_DAILY_LOSS (net={today_net:.2f} <= -{abs(max_daily_realized_loss):.2f})"
                        )
            
            if is_safe and is_entry_within_z_cap and is_conviction and is_environment_safe and cap_reason is None:
                print(f"   [BRAIN STEM] BUY {symbol} @ {price:.4f} "
                      f"(Risk={risk:.2f}, Z={entry_z:.2f}/{entry_max_z:.2f}, Prior={prior:.2f})")
                
                intent_id = f"{symbol}:{int(time.time() * 1000)}:{uuid.uuid4().hex[:8]}"
                self.pending_entry = {
                    "intent_id": intent_id,
                    "symbol": symbol,
                    "qty": frame.command.sizing_mult,
                    "bands": bands,
                    "entry_z": entry_z,
                    "mean_at_entry": val_data["mean"],
                    "sigma_at_entry": sigma,
                    "armed_at": time.time(),
                    "armed_price": price,
                }
                self.treasury.record_intent({
                    "intent_id": intent_id,
                    "ts": self.pending_entry["armed_at"],
                    "symbol": symbol,
                    "side": "BUY",
                    "qty": frame.command.sizing_mult,
                    "trigger_pulse": "ACTION",
                    "reason": "ACTION_ARMED",
                    "mode": self.execution_mode,
                    "price_ref": price,
                    "mean": val_data["mean"],
                    "sigma": sigma,
                    "z_score": entry_z,
                    "risk_score": risk,
                    "confidence": prior,
                })
                self.mean_dev_monitor_active = True
                print("   [BRAIN STEM] ACTION armed -> awaiting MINT execution (meanDev monitor ON)")
                self._emit_exec_event(
                    pulse,
                    "ARM",
                    "ACTION_ARMED",
                    symbol=symbol,
                    intent_id=intent_id,
                    qty=qty,
                    price=price,
                    risk_score=risk,
                )
            else:
                reasons = []
                if not is_safe: reasons.append(f"Risk({risk:.2f})<{min_risk:.2f}")
                if not is_entry_within_z_cap: reasons.append(f"Overextended(z={entry_z:.2f}>{entry_max_z:.2f})")
                if not is_conviction: reasons.append(f"Prior({prior:.2f})<=0.5")
                if not is_environment_safe: reasons.append("CouncilFailSafe")
                if cap_reason: reasons.append(cap_reason)
                if cap_reason:
                    self.last_exit_reason = cap_reason
                    self._emit_exec_event(pulse, "CANCEL", cap_reason, symbol=symbol)
                print(f"   [BRAIN STEM] WAIT: {', '.join(reasons)}")

        else:
            # EXIT LOGIC - Recalculate bands every pulse
            mean = val_data["mean"]
            lower = val_data["lower"]
            upper = val_data["upper"]
            sigma = max(val_data.get("sigma", 0.0), 1e-9)
            z_score = (price - mean) / sigma
            mean_rev_target_sigma = float(self.config.get("brain_stem_mean_rev_target_sigma", 0.0))
            
            exit_reason = None
            if price <= lower:
                exit_reason = f"SAFETY_VALVE_STOP (<= {lower:.2f})"
            elif price >= upper:
                exit_reason = f"SAFETY_VALVE_TAKE (>= {upper:.2f})"
            else:
                # Long-only breakout safety valve:
                # once price reaches mean-target (z >= target sigma), exit on first roll-over.
                if z_score >= mean_rev_target_sigma and self.prev_price and price < self.prev_price:
                    exit_reason = (
                        f"SAFETY_VALVE_MEAN_REV (z={z_score:.2f} "
                        f">= {mean_rev_target_sigma:.2f}, rolling)"
                    )
            
            if exit_reason:
                pnl = price - self.position["entry_price"]
                qty_held = self.position.get("qty", frame.command.sizing_mult)
                print(f"   [BRAIN STEM] SELL {symbol}: {exit_reason} PnL: {pnl:+.4f}")
                self.last_exit_reason = exit_reason
                self._fire_physical(symbol, "SELL", qty_held, price)
                if self.treasury:
                    sell_intent_id = f"{symbol}:{int(time.time()*1000)}:sell"
                    self.treasury.fire_intent(
                        sell_intent_id, symbol, "SELL", qty_held, price,
                        sigma=self.position.get("sigma_at_entry", 0.0),
                        price_ref=self.position.get("entry_price", price),
                    )
                self.position = None
                self._emit_exec_event(pulse, "EXIT", exit_reason, symbol=symbol, price=price)
            else:
                if self.treasury:
                    self.treasury.mark_to_market(symbol, price)
                print(f"   [BRAIN STEM] HOLD {symbol} @ {price:.4f}")
                self._emit_exec_event(pulse, "HOLD", "HOLD", symbol=symbol, price=price)

        self.prev_price = price
        return True

    def _fire_physical(self, symbol, side, qty, price):
        if self.execution_adapter == "alpaca" and self.client:
            try:
                # V3.3: Use the common Medulla orders logic for execution
                from Medulla.orders import buy, sell
                if side.upper() == "BUY":
                    order = buy(self.client, symbol, qty)
                else:
                    order = sell(self.client, symbol, qty)
                
                if order:
                    print(f"   [EXECUTION] {side} {symbol} (ALPACA: {order.id})")
                    return {"status": "fired", "order_id": order.id, "source": "alpaca"}
            except Exception as e:
                print(f"   [EXECUTION_ERROR] Alpaca {side} failed: {e}")
                return {"status": "error", "msg": str(e)}

        print(f"   [EXECUTION] {side} {symbol} (MOCK)")
        return {"status": "fired", "source": "mock"}

    def get_state(self):
        return {
            "risk_score": self.risk_score,
            "in_position": self.position is not None,
            "position": self.position,
            "last_exit_reason": self.last_exit_reason,
            "pending_entry": self.pending_entry,
            "mean_dev_monitor_active": self.mean_dev_monitor_active,
            "execution_mode": self.execution_mode,
            "execution_adapter": self.execution_adapter,
            "last_execution_event": self.last_execution_event,
        }
