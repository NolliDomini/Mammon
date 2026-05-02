import math
import threading
import time
import uuid
from datetime import datetime, timezone
from types import SimpleNamespace
from typing import Any, Dict, Optional

import numpy as np
from alpaca.trading.client import TradingClient
from alpaca.trading.enums import OrderSide, TimeInForce
from alpaca.trading.requests import MarketOrderRequest

from Cerebellum.Soul.brain_frame import BrainFrame
from Cerebellum.Soul.utils.timing import enforce_pulse_gate


class Trigger:
    """
    Brain Stem: The Trigger Train (V3.3 Gated Architecture).
    
    GATES (Must be OPEN):
      1. Risk Gate (Small Monte): Score > 0.5 (Safe)
      2. Valuation Gate (StdDev): Price < Mean (Undervalued)
      
    TRIGGER (Must FIRE):
      3. Engine Conviction: Prior > 0.5 (Turtle + Council)
      
    LONG ONLY:
      BUY  = Risk > 0.5  AND  Price < Mean  AND  Prior > 0.5
      SELL = (Price > Mean AND Diverging)  OR  Hard Bands (Stop/Take)
    """

    def __init__(self, api_key, api_secret, paper=True, config: Dict[str, Any] = None):
        self.config = config or {}
        self.api_key = api_key
        self.api_secret = api_secret
        self.execution_mode = str(self.config.get("execution_mode", "DRY_RUN")).upper()
        
        # Piece 119: Credential Guard & Lockdown
        self._verify_credentials()
        
        # Force paper=True unless explicitly LIVE
        is_live = self.execution_mode == "LIVE"
        self.paper = True if not is_live else False
        
        self.client = None
        self.execution_adapter = "mock"
        self._adapter_lock = threading.Lock()
        if self.execution_mode not in ["DRY_RUN", "BACKTEST"]:
            print(f"[BRAIN STEM] Initializing Alpaca Adapter (mode={self.execution_mode}, paper={self.paper})")
            self.client = TradingClient(api_key, api_secret, paper=self.paper)
            self.execution_adapter = "alpaca"
        self.rng = np.random.default_rng()
        self.treasury = None
        try:
            from Medulla.treasury.gland import TreasuryGland
            self.treasury = TreasuryGland(mode=self.execution_mode)
        except Exception as e:
            # STEM-F-P60-603: Treasury setup exception
            print(f"[STEM-F-P60-603] BRAIN STEM: Treasury unavailable: {e}")
            self.treasury = None

        # Phase 6 Target: Purge Logic Decay (Attributes handled by last_execution_event)
        self.risk_score = 0.0          
        self.prev_price = None         
        self.position = None           
        self.pending_entry = None      
        self.mean_dev_monitor_active = False
        self.last_execution_event = {}
        self.last_exit_reason = None
        self.last_trigger_score = 0.0

        # Phase 6 Target: Restore position state from Treasury on boot
        if self.execution_mode in ["PAPER", "LIVE"]:
            self._reconcile_position_state()

    def _reconcile_position_state(self):
        """Phase 6 Target: Reconcile in-memory position with Treasury ledger."""
        if not self.treasury: return
        print("[BRAIN STEM] Reconciling active positions with Treasury...")
        # Path: Treasury.get_status() provides open_positions count.
        # Implementation Detail: Fully wire multi-symbol reconciliation in next piece.

    def _verify_credentials(self):
        """Piece 119: Fail-fast credential check."""
        if not self.api_key or not self.api_secret:
            raise RuntimeError("CRITICAL: Alpaca API credentials missing from .env")
        if "your_random_" in str(self.api_key) or "your_random_" in str(self.api_secret):
            raise RuntimeError("CRITICAL: Default Alpaca credentials detected. Update .env")

    def set_execution_mode(self, mode: str):
        mode_u = str(mode or "DRY_RUN").upper()
        # Piece 119: Enforce lockdown on rebind
        is_live = mode_u == "LIVE"
        paper = True if not is_live else False
        
        with self._adapter_lock:
            self.execution_mode = mode_u
            self.config["execution_mode"] = mode_u
            self.execution_adapter = "mock"
            self.client = None
            if mode_u not in ["DRY_RUN", "BACKTEST"]:
                try:
                    print(f"[BRAIN STEM] Rebinding Alpaca Adapter (mode={mode_u}, paper={paper})")
                    self.client = TradingClient(self.api_key, self.api_secret, paper=paper)
                    self.execution_adapter = "alpaca"
                except Exception as e:
                    # Phase 6 Target: Standardized MNER for adapter failure
                    print(f"[STEM-E-P64-601] ADAPTER_REBIND_FAILED: {e}")
                    self.execution_adapter = "mock"
                    self.client = None
            try:
                from Medulla.treasury.gland import TreasuryGland
                self.treasury = TreasuryGland(mode=mode_u)
            except Exception as e:
                # STEM-E-P64-604: Treasury rebind failure
                print(f"[STEM-E-P64-604] BRAIN STEM: Treasury rebind failed for {mode_u}: {e}")
                self.treasury = None

    def _get_prior(self, frame: BrainFrame) -> float:
        """Phase 6 Target: Standardized blended conviction score."""
        w_turtle = float(self.config.get("brain_stem_w_turtle", 0.5))
        w_council = float(self.config.get("brain_stem_w_council", 0.5))
        
        # authoritative synthesis blending logic (Reconciled with Callosum)
        monte_score = float(getattr(frame.risk, "monte_score", 0.0))
        council_score = float(getattr(frame.environment, "confidence", 0.0))
        
        # Ensure weights sum to 1.0 (Piece 12)
        total_w = w_turtle + w_council
        w_t = w_turtle / total_w if total_w > 0 else 0.5
        w_c = w_council / total_w if total_w > 0 else 0.5
        
        prior = (monte_score * w_t) + (council_score * w_c)
        return float(np.clip(prior, 0.0, 1.0))

    def _trading_enabled(self, orchestrator=None) -> bool:
        if orchestrator is None:
            return True
        cfg = getattr(orchestrator, "config", {}) or {}
        trade_gate = cfg.get("trading_enabled_provider")
        if callable(trade_gate):
            try:
                return bool(trade_gate())
            except Exception as e:
                # STEM-W-P60-605: Trading enabled check failure
                print(f"[STEM-W-P60-605] BRAIN STEM: Trading enabled provider failed: {e}")
                return False
        return True

    def _is_valid_mode(self) -> bool:
        return str(self.execution_mode or "").upper() in {"DRY_RUN", "PAPER", "LIVE", "BACKTEST"}

    def _valid_execution_payload(self, frame: BrainFrame) -> tuple[bool, str, float, float]:
        symbol = str(getattr(getattr(frame, "market", None), "symbol", "") or "").strip()
        # Piece 130: Read qty from command slot
        cmd = getattr(frame, "command", None)
        qty = getattr(cmd, "qty", None)
        if qty in (None,):
            qty = 0.0
        price = getattr(getattr(frame, "structure", None), "price", 0.0)
        try:
            qty_f = float(qty)
            price_f = float(price)
        except Exception as e:
            # Phase 6 Target: Standardized MNER for invalid payload
            print(f"[STEM-E-P65-602] EXECUTION_PAYLOAD_INVALID: {e}")
            return False, symbol or "UNKNOWN", 0.0, 0.0
        
        notional = qty_f * price_f
        # Piece 130: Validate qty > 0 and notional > 0
        if (not symbol) or (qty_f <= 0.0) or (not math.isfinite(price_f)) or (price_f <= 0.0) or (notional <= 0.0):
            return False, symbol or "UNKNOWN", max(0.0, qty_f), max(0.0, price_f)
        
        # Target #62: Prioritize Gold risk caps
        max_notional = 1000.0
        standards = getattr(frame, "standards", None)
        if standards and "max_notional" in standards:
            max_notional = float(standards["max_notional"])
        else:
            max_notional = float(self.config.get("max_notional", 1000.0))
            
        if (qty_f * price_f) > max_notional:
            print(f"   [BRAIN STEM] REJECT: Notional {qty_f*price_f:.2f} > limit {max_notional}")
            return False, symbol, qty_f, price_f

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
    def _run_risk_gate(self, frame: BrainFrame, prior: float, walk_seed=None) -> float:
        """
        Small Monte (1k paths). Returns risk_score.
        PASS Condition: risk_score > 0.5
        """
        paths_per_lane = int(self.config.get("risk_gate_paths_per_lane", 333))
        total_paths = paths_per_lane * 3
        
        sigma_mult = float(self.config.get("brain_stem_sigma", 0.10))
        bias_scalar = float(self.config.get("brain_stem_bias", 0.05)) # Default small positive bias
        
        mu = float(walk_seed.mu if walk_seed else 0.0)
        # Use walk_seed.sigma if available, otherwise fallback to config-based ATR mult
        sigma = float(walk_seed.sigma if walk_seed else (frame.environment.atr * sigma_mult))
        
        noise = self.rng.normal(mu, sigma, total_paths)
        
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

        mu = float(walk_seed.mu if walk_seed else 0.0)
        sigma = float(walk_seed.sigma if walk_seed else (frame.environment.atr * sigma_mult))
        
        # Inject Bias based on Prior
        bias = (prior - 0.5) * (frame.environment.atr * bias_scalar)
        noise = self.rng.normal(mu, sigma, paths)

        final_prices = frame.structure.price + noise + bias
        mean_price = float(np.mean(final_prices))
        sigma_val = float(np.std(final_prices))

        # Piece 89: Configurable N-Sigma bands
        n_sigma = float(self.config.get("brain_stem_val_n_sigma", 1.5))
        upper = mean_price + n_sigma * sigma_val
        lower = mean_price - n_sigma * sigma_val
        
        return {
            "mean": mean_price,
            "sigma": sigma_val,
            "upper": upper,
            "lower": lower
        }

    # ------------------------------------------------------------------ #
    #  THE HUNT                                                          #
    # ------------------------------------------------------------------ #
    def load_and_hunt(self, pulse_type: str, frame: BrainFrame,
                      orchestrator=None, walk_engine=None, walk_seed=None, timeout_sec=None):
        """Piece 14: Execution edge fires at ACTION (Arm) and MINT (Fire)."""
        if not enforce_pulse_gate(pulse_type, ["ACTION", "MINT"], "Brain_Stem"):
            self.prev_price = getattr(getattr(frame, "structure", None), "price", None)
            return True

        pulse = str(pulse_type or "").upper()

        if not self._is_valid_mode():
            self.last_exit_reason = f"MODE_GATE_CANCEL (invalid mode={self.execution_mode})"
            self._emit_exec_event(pulse, "MODE_GATE", self.last_exit_reason)
            self.prev_price = getattr(getattr(frame, "structure", None), "price", None)
            return True

        # Always compute valuation — every ACTION/MINT frame must have valid data
        _prior = self._get_prior(frame)
        try:
            _val = self._run_valuation_gate(frame, _prior, walk_seed)
        except TypeError:
            _val = self._run_valuation_gate(frame, _prior)
        if getattr(frame, "valuation", None) is None:
            frame.valuation = SimpleNamespace()
        frame.valuation.mean = float(_val["mean"])
        frame.valuation.std_dev = float(_val["sigma"])
        frame.valuation.upper_band = float(_val["upper"])
        frame.valuation.lower_band = float(_val["lower"])
        frame.valuation.valuation_source = "TRIGGER_GATE"
        _vp = float(frame.structure.price)
        _vs = float(_val["sigma"])
        _vm = float(_val["mean"])
        if _vs > 0 and _vm > 0:
            frame.valuation.z_distance = (_vm - _vp) / _vs
        else:
            frame.valuation.z_distance = 0.0

        # MINT finalizes pending ACTION approvals.
        if pulse == "MINT":
            if self.pending_entry is not None and self.position is None:
                intent_id = self.pending_entry.get("intent_id")
                symbol = self.pending_entry["symbol"]
                # Piece 129: Read qty from command slot (hydrated by AllocationGland)
                qty = float(getattr(frame.command, "qty", 0.0))
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
                
                # V3.3: Use the mean and sigma captured at ACTION to check for reversion
                mean_ref = self.pending_entry.get("mean_at_entry", price)
                sigma_ref = max(self.pending_entry.get("sigma_at_entry", 1e-9), 1e-9)
                z_score = (frame.structure.price - mean_ref) / sigma_ref
                
                # V3.3 GATED: Mean reversion kill logic between ACTION and MINT
                cancel_sigma = float(self.config.get("brain_stem_mean_dev_cancel_sigma", 0.0))
                cancel_pending = z_score >= cancel_sigma

                if cancel_pending:
                    self.last_exit_reason = (
                        f"MEAN_DEV_CANCEL (z={z_score:.2f} >= {cancel_sigma:.2f})"
                    )
                    if self.treasury and intent_id:
                        self.treasury.cancel_intent(intent_id, symbol, self.last_exit_reason)
                    print(
                        f"   [BRAIN STEM] MINT CANCEL {symbol} @ {price:.4f} "
                        f"({self.last_exit_reason})"
                    )
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
                        f"   [BRAIN STEM] MINT FIRE {symbol} @ {price:.4f} "
                        f"(meanDev monitor OFF)"
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
                            "bands": self.pending_entry.get("bands", {}),
                            "symbol": symbol,
                            "qty": qty,  # M1 fix: store qty for exit path
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
                            total_cost_bps=float(getattr(getattr(frame, "execution", None), "total_cost_bps", 0.0) or 0.0),
                            z_distance=float(getattr(getattr(frame, "valuation", None), "z_distance", 0.0) or 0.0)
                        )
            self.pending_entry = None
            self.mean_dev_monitor_active = False
            self.prev_price = frame.structure.price
            return True

        # Brain Stem execution logic is keyed off ACTION pulse for pre-fire checks.
        # Enforce policy ownership: Brain Stem cannot independently approve.
        # Inhibitor-First: Default to False/0 if missing.
        ready_to_fire = bool(getattr(frame.command, "ready_to_fire", False))
        approved = int(getattr(frame.command, "approved", 0))
        
        if not ready_to_fire or approved != 1:
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
                # Piece 13: Reconciled terminal state via TreasuryGland
                self.treasury.record_rejected_intent(
                    intent_id=intent_id,
                    symbol=symbol,
                    qty=qty,
                    price=price,
                    reason=self.last_exit_reason
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
        
        # 1. GATE 1: RISK (Using shared walk_seed)
        try:
            risk = self._run_risk_gate(frame, prior, walk_seed)
        except TypeError:
            # Backward-compat for tests/overrides that still use the legacy 2-arg signature.
            risk = self._run_risk_gate(frame, prior)
        
        # 2. GATE 2: VALUATION (Using shared walk_seed)
        val_data = self._run_valuation_gate(frame, prior, walk_seed)
        bands = val_data
        self.last_trigger_score = risk  # Telemetry
        
        # Contract compatibility: some test/dry-run frames do not pre-seed valuation.
        if getattr(frame, "valuation", None) is None:
            frame.valuation = SimpleNamespace()

        # Piece 88: Write to frame.valuation
        frame.valuation.mean = float(val_data["mean"])
        frame.valuation.std_dev = float(val_data["sigma"])
        frame.valuation.upper_band = float(val_data["upper"])
        frame.valuation.lower_band = float(val_data["lower"])
        frame.valuation.valuation_source = "TRIGGER_GATE"
        
        # Calculate z_distance
        price = float(frame.structure.price)
        sigma = float(val_data["sigma"])
        mean = float(val_data["mean"])
        
        # Piece 90: Zero guard
        if sigma > 0 and mean > 0:
            frame.valuation.z_distance = (mean - price) / sigma
        else:
            frame.valuation.z_distance = 0.0
        
        # ---- LOGIC ----
        if self.position is None:
            # ENTRY LOGIC
            is_safe = risk > 0.5
            is_undervalued = price < val_data["mean"]
            
            # V3.3: Council is a fail-safe only (Environmental Confidence)
            min_council = float(self.config.get("gatekeeper_min_council", 0.5))
            is_environment_safe = frame.environment.confidence >= min_council
            is_conviction = prior > 0.5
            cap_reason = None

            max_notional = float(self.config.get("max_notional_per_order", 0.0) or 0.0)
            qty = float(frame.command.qty or 0.0)  # C1 fix: use command.qty from AllocationGland
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
            
            if is_safe and is_undervalued and is_conviction and is_environment_safe and cap_reason is None:
                print(f"   [BRAIN STEM] BUY {symbol} @ {price:.4f} "
                      f"(Risk={risk:.2f}, Val={price-val_data['mean']:.2f}, Prior={prior:.2f})")
                
                sigma = max(val_data.get("sigma", 0.0), 1e-9)
                entry_z = (price - val_data["mean"]) / sigma
                intent_id = f"{symbol}:{int(time.time() * 1000)}:{uuid.uuid4().hex[:8]}"
                self.pending_entry = {
                    "intent_id": intent_id,
                    "symbol": symbol,
                    "qty": float(frame.command.qty or 0.0),  # C1 fix
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
                    "qty": float(frame.command.qty or 0.0),  # C1 fix
                    "trigger_pulse": "ACTION",
                    "reason": "ACTION_ARMED",
                    "mode": self.execution_mode,
                    "price_ref": price,
                    "mean": val_data["mean"],
                    "sigma": sigma,
                    "z_score": entry_z,
                    "risk_score": risk,
                    "confidence": prior,
                    # Piece 134: Add Phase 1 context
                    "pre_trade_cost_bps": float(getattr(getattr(frame, "execution", None), "total_cost_bps", 0.0) or 0.0),
                    "spread_regime": str(getattr(getattr(frame, "environment", None), "spread_regime", "UNKNOWN")),
                    "z_distance": float(getattr(getattr(frame, "valuation", None), "z_distance", 0.0) or 0.0)
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
                    total_cost_bps=float(getattr(getattr(frame, "execution", None), "total_cost_bps", 0.0) or 0.0),
                    z_distance=float(getattr(getattr(frame, "valuation", None), "z_distance", 0.0) or 0.0)
                )
            else:
                reasons = []
                if not is_safe: reasons.append(f"Risk({risk:.2f})<=0.5")
                if not is_undervalued: reasons.append("Overvalued")
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
                print(f"   [BRAIN STEM] SELL {symbol}: {exit_reason} PnL: {pnl:+.4f}")
                self.last_exit_reason = exit_reason
                # Use original position quantity for exit, not current sizing mult
                sell_qty = self.position.get("qty", float(frame.command.qty or 0.0))  # M1 fix
                fire_result = self._fire_physical(symbol, "SELL", sell_qty, price)
                if not isinstance(fire_result, dict):
                    fire_result = {"status": "fired", "source": "compat"}
                if fire_result.get("status") == "fired" and self.treasury is not None:
                    exit_intent_id = f"{symbol}:{int(time.time() * 1000)}:{uuid.uuid4().hex[:8]}"
                    self.treasury.record_intent({
                        "intent_id": exit_intent_id,
                        "ts": time.time(),
                        "symbol": symbol,
                        "side": "SELL",
                        "qty": sell_qty,
                        "trigger_pulse": pulse,
                        "reason": exit_reason,
                        "mode": self.execution_mode,
                        "price_ref": price,
                        "mean": float(val_data.get("mean", price)),
                        "sigma": float(val_data.get("sigma", 0.0)),
                        "z_score": z_score,
                        "risk_score": self.risk_score,
                        "confidence": prior,
                    })
                    self.treasury.fire_intent(
                        exit_intent_id,
                        symbol,
                        "SELL",
                        sell_qty,
                        price,
                        sigma=float(val_data.get("sigma", 0.0)),
                        price_ref=price,
                        pulse_type=pulse,
                    )
                self.position = None
                self._emit_exec_event(pulse, "EXIT", exit_reason, symbol=symbol, price=price)
            else:
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
                # STEM-F-P60-606: Broker submission failure
                print(f"[STEM-F-P60-606] BRAIN STEM: Alpaca {side} failed: {e}")
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
