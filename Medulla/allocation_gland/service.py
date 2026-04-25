import numpy as np
from typing import Dict, Any

from Hippocampus.Context.mner import emit_mner

class AllocationGland:
    """
    Medulla: Allocation Gland (Piece 94).
    Calculates precise order quantity based on mean-reversion conviction and cost.
    """
    def __init__(self):
        self.last_telemetry = {}

    @staticmethod
    def compute(equity: float, risk_pct: float, conviction: float, stop_distance: float) -> float:
        """
        Deterministic sizing kernel used by Gatekeeper runtime.
        qty = (equity * risk_pct * conviction) / stop_distance
        """
        try:
            equity_f = float(equity)
            risk_f = float(risk_pct)
            conviction_f = float(np.clip(float(conviction), 0.0, 1.0))
            stop_f = abs(float(stop_distance))
        except Exception:
            return 0.0
        if equity_f <= 0.0 or risk_f <= 0.0 or stop_f <= 0.0:
            return 0.0
        return float(max(0.0, (equity_f * risk_f * conviction_f) / stop_f))

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
            max_z = frame.standards.get("alloc_max_z", frame.standards.get("max_z", 2.0))
            raw_conviction = np.clip(z_distance / max_z, 0.0, 1.0)
            
            # Piece 99: Cost Penalty
            # formula: total_cost_bps / cost_penalty_divisor
            total_cost_bps = frame.execution.total_cost_bps
            cost_penalty_divisor = frame.standards.get(
                "alloc_cost_penalty_divisor",
                frame.standards.get("cost_penalty_divisor", 100.0),
            )
            cost_penalty = total_cost_bps / cost_penalty_divisor if cost_penalty_divisor > 0 else 0.0
            
            # Piece 100: Adjusted Conviction
            # formula: raw_conviction * (1.0 - clamp(cost_penalty, 0, max_cost_penalty))
            max_cost_penalty = frame.standards.get(
                "alloc_max_cost_penalty",
                frame.standards.get("max_cost_penalty", 0.5),
            )
            clamped_penalty = np.clip(cost_penalty, 0.0, max_cost_penalty)
            adjusted_conviction = raw_conviction * (1.0 - clamped_penalty)
            
            # Write to frame for telemetry
            frame.command.cost_adjusted_conviction = float(adjusted_conviction)
            
            # Piece 101: Raw Quantity
            # formula: (equity * risk_per_trade_pct * adjusted_conviction) / stop_distance
            equity = frame.standards.get("alloc_equity", frame.standards.get("equity", 10000.0))
            risk_pct = frame.standards.get(
                "alloc_risk_per_trade_pct",
                frame.standards.get("risk_per_trade_pct", 0.01),
            ) # 1% default
            
            # C2 fix: Initialize defaults before branch to prevent NameError
            price = float(frame.structure.price) if hasattr(frame.structure, 'price') else 0.0
            stop_distance = 0.0
            raw_qty = 0.0
            size_reason = "NONE"

            # Piece 106: Invalid Risk Inputs
            if equity <= 0 or risk_pct <= 0:
                # ALLOC-E-SIZE-901: INVALID_RISK_INPUTS
                emit_mner(
                    "ALLOC-E-SIZE-901",
                    "ALLOC_INVALID_RISK_INPUTS",
                    source="Medulla.allocation_gland.service.AllocationGland.allocate",
                    details={"equity": equity, "risk_pct": risk_pct},
                    echo=True,
                )
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
                    emit_mner(
                        "ALLOC-E-SIZE-902",
                        "ALLOC_STOP_DISTANCE_INVALID",
                        source="Medulla.allocation_gland.service.AllocationGland.allocate",
                        details={"stop_distance": stop_distance},
                        echo=True,
                    )
                    raw_qty = 0.0
                    size_reason = "NO_TRADE_STOP_INVALID"
                else:
                    raw_qty = (equity * risk_pct * adjusted_conviction) / stop_distance
                    if adjusted_conviction < raw_conviction:
                        size_reason = "SIZED_COST_PENALIZED"
                
            # Piece 102: Hard Caps
            max_notional = frame.standards.get(
                "alloc_max_notional",
                frame.standards.get("max_notional", 10000.0),
            )
            max_qty_cap = frame.standards.get(
                "alloc_max_qty",
                frame.standards.get("max_qty", 100.0),
            )  # C3 fix: enforce max_qty
            max_qty_from_notional = max_notional / price if price > 0 else 0.0
            
            # 1. Quantity Cap (notional AND absolute)
            qty = min(raw_qty, max_qty_from_notional, max_qty_cap)
            if qty < raw_qty:
                # Piece 108: MNER ALLOC-E-SIZE-903
                emit_mner(
                    "ALLOC-E-SIZE-903",
                    "ALLOC_RISK_CAP_APPLIED",
                    source="Medulla.allocation_gland.service.AllocationGland.allocate",
                    details={"raw_qty": float(raw_qty), "capped_qty": float(qty)},
                    echo=True,
                )
                size_reason = "SIZED_CAP_CLAMPED"
                
            # 2. Minimum Qty check
            min_qty = frame.standards.get("alloc_min_qty", frame.standards.get("min_qty", 0.001))
            if qty > 0 and qty < min_qty:
                qty = 0.0
                size_reason = "NO_TRADE_BELOW_MIN"

            # Piece 102 & 105: Write to BrainFrame
            frame.command.qty = float(qty)
            frame.command.sizing_mult = float(qty)  # Brain Stem reads sizing_mult, not qty
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
            emit_mner(
                "ALLOC-E-SIZE-904",
                "ALLOC_RUNTIME_ERROR",
                source="Medulla.allocation_gland.service.AllocationGland.allocate",
                details={"error": str(e)},
                echo=True,
            )
            self.last_telemetry = {"status": "error", "msg": str(e)}
            # Piece 127: Fail closed
            frame.command.qty = 0.0
            frame.command.ready_to_fire = False
            frame.command.approved = 0
            return self.last_telemetry

    def get_state(self) -> Dict[str, Any]:
        return self.last_telemetry
