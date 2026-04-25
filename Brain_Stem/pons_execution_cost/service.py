import numpy as np
from typing import Dict, Any

class PonsExecutionCost:
    """
    Brain_Stem: Pons Execution Cost Engine (Piece 68).
    Evaluates pre-trade friction: Spread + Impact + Volatility.
    """
    def __init__(self):
        self.last_telemetry = {}

    def estimate(self, pulse_type: str, frame: Any) -> Dict[str, Any]:
        """
        Piece 68: Core estimation contract.
        Writes to frame.execution.
        """
        try:
            # Piece 69: Pulse Gate
            if pulse_type != "ACTION":
                return {"status": "skipped", "reason": "pulse_gate"}

            # 1. SLIPPAGE (TCA Standard)
            # Piece 70: Half-spread component
            spread_bps = frame.environment.bid_ask_bps
            half_spread_bps = spread_bps / 2.0
            
            # Piece 79: Invalid Liquidity Check
            if spread_bps < 0 or frame.environment.atr <= 0:
                # PONS-E-COST-802: INVALID_LIQUIDITY
                print(f"[PONS-E-COST-802] PONS: Invalid liquidity data (spread={spread_bps}, atr={frame.environment.atr}).")
                # Default to high-cost fallback
                half_spread_bps = max(half_spread_bps, 10.0) 
            
            # Piece 71: Market Impact
            impact_scalar = frame.standards.get("slippage_impact_scalar", 0.1)
            notional = frame.command.notional
            # C5 fix: Use raw average volume, not normalized score
            if not frame.market.ohlcv.empty and "volume" in frame.market.ohlcv.columns:
                avg_volume = float(frame.market.ohlcv["volume"].iloc[-50:].mean())
            else:
                avg_volume = 0.0
            
            # Piece 78: Missing Input Check
            if notional <= 0 or avg_volume <= 0:
                # PONS-E-COST-801: MISSING_ORDER_INPUT
                print(f"[PONS-E-COST-801] PONS: Missing trade inputs (notional={notional}, avg_vol={avg_volume}).")
                # Default to half-spread + volatility (bypass impact)
                impact_bps = 0.0
            else:
                impact_ratio = notional / avg_volume
                impact_bps = impact_scalar * (impact_ratio ** 0.5)
            
            # Piece 72: Volatility Cost
            vol_scalar = frame.standards.get("slippage_vol_scalar", 0.05)
            close = float(frame.market.ohlcv["close"].iloc[-1]) if not frame.market.ohlcv.empty else 1.0
            atr = frame.environment.atr
            atr_bps = (atr / close) * 10000.0 if close > 0 else 0.0
            vol_cost_bps = vol_scalar * atr_bps

            # Piece 73: Total Slippage
            slippage_bps = half_spread_bps + impact_bps + vol_cost_bps
            max_slippage = frame.standards.get("max_slippage_bps", 50.0)
            slippage_bps = float(np.clip(slippage_bps, 0.0, max_slippage))

            # 2. FEES
            # Piece 74: Market order fees
            fee_bps = frame.standards.get("fee_taker_bps")
            if fee_bps is None:
                fallback_pct = frame.standards.get("fee_fallback_pct")
                if fallback_pct is None:
                    # Piece 80: MNER PONS-E-COST-803
                    print("[PONS-E-COST-803] PONS: Fee schedule missing in standards. Using 30bps ultra-pessimistic fallback.")
                    fee_bps = 30.0
                else:
                    fee_bps = fallback_pct * 10000.0
            
            # 3. TOTAL COST
            # Piece 76: total_cost_bps = slippage + expected_fee
            total_cost_bps = slippage_bps + float(fee_bps)

            # Piece 77: Write to BrainFrame
            frame.execution.expected_slippage_bps = slippage_bps
            frame.execution.expected_fee_bps = float(fee_bps)
            frame.execution.total_cost_bps = total_cost_bps

            self.last_telemetry = {
                "status": "success",
                "bid_ask_bps": spread_bps,
                "half_spread_bps": half_spread_bps,
                "impact_bps": impact_bps,
                "vol_cost_bps": vol_cost_bps,
                "slippage_bps": slippage_bps,
                "fee_bps": float(fee_bps),
                "total_cost_bps": total_cost_bps,
                "impact_inputs": {"notional": notional, "avg_vol": avg_volume},
                "vol_inputs": {"atr_bps": atr_bps}
            }
            return self.last_telemetry
        except Exception as e:
            # Piece 81: MNER PONS-E-COST-804
            print(f"[PONS-E-COST-804] PONS: Model computation error: {e}")
            self.last_telemetry = {"status": "error", "reason": "computation_error"}
            # Piece 126: Conservative guard
            max_cap = frame.standards.get("max_cost_cap_bps", 100.0)
            frame.execution.total_cost_bps = float(max_cap)
            return self.last_telemetry

    def get_state(self) -> Dict[str, Any]:
        return self.last_telemetry
