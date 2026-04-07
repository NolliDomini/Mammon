import unittest
import pandas as pd
import numpy as np
from Medulla.allocation_gland.service import AllocationGland
from Cerebellum.Soul.brain_frame.service import BrainFrame

class TestAllocationGlandContract(unittest.TestCase):
    def setUp(self):
        self.alloc = AllocationGland()
        self.frame = BrainFrame()
        # Mock standards
        self.frame.standards = {
            "alloc_max_z": 2.0,
            "alloc_cost_penalty_divisor": 100.0,
            "alloc_max_cost_penalty": 0.5,
            "alloc_equity": 10000.0,
            "alloc_risk_per_trade_pct": 0.01, # 1% = $100 risk
            "alloc_max_notional": 5000.0,
            "alloc_min_qty": 0.0001
        }
        # Mock valuation: Price 100, Mean 105, Sigma 5
        # z_distance = (105-100)/5 = 1.0
        self.frame.structure.price = 100.0
        self.frame.valuation.mean = 105.0
        self.frame.valuation.std_dev = 5.0
        self.frame.valuation.lower_band = 95.0 # stop distance = 5.0
        self.frame.valuation.z_distance = 1.0
        
        # Mock execution cost: 10bps
        self.frame.execution.total_cost_bps = 10.0

    def test_piece_110_happy_path(self):
        """Piece 110: Sized position when price < mean."""
        self.alloc.allocate("ACTION", self.frame)
        
        # 1. Raw Conviction = 1.0 / 2.0 = 0.5
        # 2. Cost Penalty = 10 / 100 = 0.1
        # 3. Adjusted Conviction = 0.5 * (1.0 - 0.1) = 0.45
        # 4. Raw Qty = ($100 risk * 0.45 conviction) / $5.0 stop_dist = $45 / 5.0 = 9.0 shares
        
        self.assertEqual(self.frame.command.qty, 9.0)
        self.assertEqual(self.frame.command.size_reason, "SIZED_COST_PENALIZED")
        self.assertEqual(self.frame.command.notional, 900.0)
        self.assertAlmostEqual(self.frame.command.risk_used, 0.0045) # ($9*5)/$10000

    def test_piece_111_price_at_mean(self):
        """Piece 111: Price at mean -> NO_TRADE_ABOVE_MEAN."""
        # Price 105, Mean 105, Sigma 5 -> z = 0.0
        self.frame.structure.price = 105.0
        self.frame.valuation.mean = 105.0
        self.frame.valuation.z_distance = 0.0
        
        self.alloc.allocate("ACTION", self.frame)
        
        self.assertEqual(self.frame.command.qty, 0.0)
        self.assertEqual(self.frame.command.size_reason, "NO_TRADE_ABOVE_MEAN")
        self.assertFalse(self.frame.command.ready_to_fire)

    def test_piece_112_price_above_mean(self):
        """Piece 112: Price above mean -> NO_TRADE_ABOVE_MEAN."""
        # Price 110, Mean 105, Sigma 5 -> z = -1.0 (mean - price) / sigma
        self.frame.structure.price = 110.0
        self.frame.valuation.mean = 105.0
        self.frame.valuation.z_distance = -1.0
        
        self.alloc.allocate("ACTION", self.frame)
        
        self.assertEqual(self.frame.command.qty, 0.0)
        self.assertEqual(self.frame.command.size_reason, "NO_TRADE_ABOVE_MEAN")
        self.assertFalse(self.frame.command.ready_to_fire)

    def test_piece_113_hard_cap_clamp(self):
        """Piece 113: Verify quantity is clamped by max notional."""
        # Setup very large conviction and low stop distance to trigger large raw_qty
        self.frame.valuation.z_distance = 2.0 # conviction 1.0
        self.frame.valuation.lower_band = 99.9 # stop distance 0.1
        self.frame.structure.price = 100.0
        self.frame.standards["alloc_max_notional"] = 1000.0
        self.frame.execution.total_cost_bps = 0.0 # no penalty
        
        # Raw Qty = ($100 risk * 1.0 conv) / $0.1 stop_dist = 1000 shares
        # Notional = 1000 * $100 = $100,000. 
        # Capped Notional = $1000 -> Max Qty = 10 shares
        
        self.alloc.allocate("ACTION", self.frame)
        
        self.assertEqual(self.frame.command.qty, 10.0)
        self.assertEqual(self.frame.command.size_reason, "SIZED_CAP_CLAMPED")
        self.assertEqual(self.frame.command.notional, 1000.0)

    def test_piece_114_high_cost_penalty(self):
        """Piece 114: High execution cost reduces conviction and qty."""
        self.frame.valuation.z_distance = 2.0 # raw conviction 1.0
        self.frame.valuation.lower_band = 90.0 # stop distance 10.0
        self.frame.structure.price = 100.0
        
        # Scenario A: Low Cost (10 bps)
        self.frame.execution.total_cost_bps = 10.0
        self.alloc.allocate("ACTION", self.frame)
        qty_low_cost = self.frame.command.qty # Conv 0.9 -> $90 / 10 = 9 shares
        
        # Scenario B: High Cost (40 bps)
        self.frame.execution.total_cost_bps = 40.0
        self.alloc.allocate("ACTION", self.frame)
        qty_high_cost = self.frame.command.qty # Penalty = 40/100 = 0.4. Conv = 1.0*(1-0.4) = 0.6. $60/10 = 6 shares
        
        self.assertLess(qty_high_cost, qty_low_cost)
        self.assertEqual(qty_high_cost, 6.0)
        self.assertEqual(self.frame.command.size_reason, "SIZED_COST_PENALIZED")

    def test_piece_115_zero_stop_distance(self):
        """Piece 115: Zero stop distance -> NO_TRADE_STOP_INVALID."""
        # Price 100, Stop 100 -> dist = 0
        self.frame.structure.price = 100.0
        self.frame.valuation.lower_band = 100.0
        self.frame.valuation.z_distance = 1.0
        
        self.alloc.allocate("ACTION", self.frame)
        
        self.assertEqual(self.frame.command.qty, 0.0)
        self.assertEqual(self.frame.command.size_reason, "NO_TRADE_STOP_INVALID")
        self.assertFalse(self.frame.command.ready_to_fire)

    def test_piece_116_min_qty_reject(self):
        """Piece 116: Reject order if qty < alloc_min_qty."""
        self.frame.standards["alloc_min_qty"] = 1.0
        # Setup very low conviction to produce small qty
        self.frame.valuation.z_distance = 0.01 
        self.frame.valuation.lower_band = 90.0 # 10.0 stop dist
        self.frame.structure.price = 100.0
        
        self.alloc.allocate("ACTION", self.frame)
        
        # Raw conviction = 0.01 / 2.0 = 0.005
        # Raw Qty = ($100 * 0.005) / 10 = $0.5 / 10 = 0.05 shares
        # 0.05 < 1.0 -> Reject
        
        self.assertEqual(self.frame.command.qty, 0.0)
        self.assertEqual(self.frame.command.size_reason, "NO_TRADE_BELOW_MIN")

    def test_piece_117_pulse_gate(self):
        """Piece 117: Verify allocation only runs on ACTION pulse."""
        # 1. SEED pulse
        self.alloc.allocate("SEED", self.frame)
        self.assertEqual(self.frame.command.qty, 0.0) # Unchanged from default
        
        # 2. MINT pulse
        self.alloc.allocate("MINT", self.frame)
        self.assertEqual(self.frame.command.qty, 0.0)

if __name__ == "__main__":
    unittest.main()
