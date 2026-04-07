import numpy as np
from typing import Dict, Any

class AllocationGland:
    """
    Medulla: Allocation Gland (Piece 94).
    Calculates precise order quantity based on mean-reversion conviction and cost.
    """
    def __init__(self):
        self.last_telemetry = {}

    def allocate(self, pulse_type: str, frame: Any):
        """
        Piece 94: Core allocation contract.
        Writes to frame.command.
        """
        try:
            # Piece 95: Pulse Gate
            if pulse_type != "ACTION":
                return

            # Piece 96: Read valuation metrics
            z_distance = frame.valuation.z_distance
            
            # Piece 97: Raw Conviction
            # formula: clamp(z_distance / max_z, 0.0, 1.0)
            max_z = frame.standards.get("max_z", 2.0)
            raw_conviction = np.clip(z_distance / max_z, 0.0, 1.0)
            
            # Piece 99: Cost Penalty
            # formula: total_cost_bps / cost_penalty_divisor
            total_cost_bps = frame.execution.total_cost_bps
            cost_penalty_divisor = frame.standards.get("cost_penalty_divisor", 100.0)
            cost_penalty = total_cost_bps / cost_penalty_divisor if cost_penalty_divisor > 0 else 0.0
            
            # Piece 100: Adjusted Conviction
            # formula: raw_conviction * (1.0 - clamp(cost_penalty, 0, max_cost_penalty))
            max_cost_penalty = frame.standards.get("max_cost_penalty", 0.5)
            clamped_penalty = np.clip(cost_penalty, 0.0, max_cost_penalty)
            adjusted_conviction = raw_conviction * (1.0 - clamped_penalty)
            
            # Write to frame for telemetry
            frame.command.cost_adjusted_conviction = float(adjusted_conviction)
            
            # Piece 101: Raw Quantity
            # formula: (equity * risk_per_trade_pct * adjusted_conviction) / stop_distance
            equity = frame.standards.get("equity", 10000.0)
            risk_pct = frame.standards.get("risk_per_trade_pct", 0.01) # 1% default
            
            # C2 fix: Initialize defaults before branch to prevent NameError
            price = float(frame.structure.price) if hasattr(frame.structure, 'price') else 0.0
            stop_distance = 0.0
            raw_qty = 0.0
            size_reason = "NONE"

            # Piece 106: Invalid Risk Inputs
            if equity <= 0 or risk_pct <= 0:
                # ALLOC-E-SIZE-901: INVALID_RISK_INPUTS
                print(f"[ALLOC-E-SIZE-901] ALLOC: Invalid risk inputs (equity={equity}, risk_pct={risk_pct}).")
                raw_qty = 0.0
                size_reason = "NO_TRADE_ZERO_EQUITY" if equity <= 0 else "NO_TRADE_INVALID_RISK"
            else:
                stop_price = float(frame.valuation.lower_band)
                stop_distance = abs(price - stop_price)
                
                size_reason = "SIZED_MEAN_REVERSION"
                if z_distance <= 0:
                    raw_qty = 0.0
                    size_reason = "NO_TRADE_ABOVE_MEAN"
                elif stop_distance <= 0:
                    # Piece 107: MNER ALLOC-E-SIZE-902
                    print(f"[ALLOC-E-SIZE-902] ALLOC: Zero or negative stop distance ({stop_distance}).")
                    raw_qty = 0.0
                    size_reason = "NO_TRADE_STOP_INVALID"
                else:
                    raw_qty = (equity * risk_pct * adjusted_conviction) / stop_distance
                    if adjusted_conviction < raw_conviction:
                        size_reason = "SIZED_COST_PENALIZED"
                
            # Piece 102: Hard Caps
            max_notional = frame.standards.get("max_notional", 10000.0)
            max_qty_cap = frame.standards.get("max_qty", 100.0)  # C3 fix: enforce max_qty
            max_qty_from_notional = max_notional / price if price > 0 else 0.0
            
            # 1. Quantity Cap (notional AND absolute)
            qty = min(raw_qty, max_qty_from_notional, max_qty_cap)
            if qty < raw_qty:
                # Piece 108: MNER ALLOC-E-SIZE-903
                print(f"[ALLOC-E-SIZE-903] ALLOC: Risk cap breach. Raw={raw_qty:.4f} -> Capped={qty:.4f}")
                size_reason = "SIZED_CAP_CLAMPED"
                
            # 2. Minimum Qty check
            min_qty = frame.standards.get("min_qty", 0.001)
            if qty > 0 and qty < min_qty:
                qty = 0.0
                size_reason = "NO_TRADE_BELOW_MIN"

            # Piece 102 & 105: Write to BrainFrame
            frame.command.qty = float(qty)
            frame.command.notional = float(qty * price)
            frame.command.size_reason = str(size_reason)
            # Piece 105: Calculate risk_used
            frame.command.risk_used = (qty * stop_distance) / equity if equity > 0 else 0.0
            
            # Piece 104: No-trade policy
            if qty <= 0:
                frame.command.ready_to_fire = False
                frame.command.approved = 0
                
            self.last_telemetry = {
                "status": "success",
                "z_distance": z_distance,
                "raw_conviction": float(raw_conviction),
                "adjusted_conviction": float(adjusted_conviction),
                "final_qty": float(qty),
                "size_reason": size_reason
            }
        except Exception as e:
            # Piece 109: MNER ALLOC-E-SIZE-904
            print(f"[ALLOC-E-SIZE-904] ALLOC: Allocator runtime error: {e}")
            self.last_telemetry = {"status": "error", "msg": str(e)}
            # Piece 127: Fail closed
            frame.command.qty = 0.0
            frame.command.ready_to_fire = False
            frame.command.approved = 0
            return self.last_telemetry

    def get_state(self) -> Dict[str, Any]:
        return self.last_telemetry
