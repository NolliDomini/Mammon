import unittest
import pandas as pd
import numpy as np
from Brain_Stem.pons_execution_cost.service import PonsExecutionCost
from Cerebellum.Soul.brain_frame.service import BrainFrame

class TestPonsCostContract(unittest.TestCase):
    def setUp(self):
        self.pons = PonsExecutionCost()
        self.frame = BrainFrame()
        # Mock standards
        self.frame.standards = {
            "pons_impact_scalar": 0.1,
            "pons_vol_scalar": 0.05,
            "pons_max_slippage_bps": 50.0,
            "fee_taker_bps": 10.0
        }
        # Mock environment
        self.frame.environment.bid_ask_bps = 4.0 # half-spread = 2.0
        self.frame.environment.atr = 1.0 # 100 bps
        self.frame.environment.volume_score = 10000.0
        
        # Mock command
        self.frame.command.notional = 1000.0 # 10% of avg volume for impact calc
        
        # Mock market
        self.frame.market.ohlcv = pd.DataFrame({"close": [100.0]})

    def test_piece_82_happy_path(self):
        """Piece 82: Correct slippage, fee, total cost."""
        res = self.pons.estimate("ACTION", self.frame)
        
        # 1. Half-spread = 4 / 2 = 2.0 bps
        # 2. Impact = 0.1 * sqrt(1000 / 10000) = 0.1 * sqrt(0.1) = 0.1 * 0.316 = 0.0316 bps
        # 3. Vol cost = 0.05 * 100 bps = 5.0 bps
        # Total Slippage = 2.0 + 0.0316 + 5.0 = 7.0316 bps
        # 4. Fee = 10.0 bps
        # Total Cost = 7.0316 + 10.0 = 17.0316 bps
        
        self.assertAlmostEqual(self.frame.execution.expected_slippage_bps, 7.0316, places=4)
        self.assertAlmostEqual(self.frame.execution.expected_fee_bps, 10.0)
        self.assertAlmostEqual(self.frame.execution.total_cost_bps, 17.0316, places=4)
        self.assertEqual(res["status"], "success")

    def test_piece_83_half_spread_dominance(self):
        """Piece 83: Half-spread dominates when impact/vol are zero/low."""
        # Setup negligible impact/vol
        self.frame.command.notional = 0.0001
        self.frame.environment.volume_score = 1000000.0
        self.frame.environment.atr = 0.00001
        self.frame.environment.bid_ask_bps = 10.0 # half-spread = 5.0
        
        self.pons.estimate("ACTION", self.frame)
        
        # Slippage should be slightly above 5.0
        self.assertGreaterEqual(self.frame.execution.expected_slippage_bps, 5.0)
        self.assertLess(self.frame.execution.expected_slippage_bps, 5.1)

    def test_piece_84_high_atr_spike(self):
        """Piece 84: High ATR -> vol_cost spike."""
        # Setup high ATR (5% move per bar)
        self.frame.environment.atr = 5.0 # 500 bps
        self.frame.environment.bid_ask_bps = 2.0 # half-spread = 1.0
        self.frame.command.notional = 0.0001 # negligible impact
        
        self.pons.estimate("ACTION", self.frame)
        
        # Expected Vol Cost: 0.05 * 500 bps = 25.0 bps
        # Total slippage: 1.0 + ~0 + 25.0 = ~26.0 bps
        self.assertGreaterEqual(self.frame.execution.expected_slippage_bps, 26.0)

    def test_piece_85_low_volume_impact_spike(self):
        """Piece 85: Low relative volume -> impact spike."""
        # Setup low volume relative to notional
        self.frame.environment.volume_score = 100.0 # very low liquidity
        self.frame.command.notional = 100.0 # trading 100% of avg volume
        self.frame.environment.bid_ask_bps = 2.0 # half-spread = 1.0
        self.frame.environment.atr = 0.00001 # negligible vol cost
        
        self.pons.estimate("ACTION", self.frame)
        
        # Expected Impact: 0.1 * sqrt(100 / 100) = 0.1 * 1.0 = 0.1 bps. 
        # Wait, 0.1 bps is tiny. Let's trade more to see a real spike.
        self.frame.command.notional = 10000.0 # 100x avg volume
        self.pons.estimate("ACTION", self.frame)
        # Impact: 0.1 * sqrt(10000 / 100) = 0.1 * 10 = 1.0 bps
        # If I want a spike, I need a larger scalar or larger notional.
        
        # Let's use scalar 1.0 for this test to see the sqrt behavior
        self.frame.standards["pons_impact_scalar"] = 1.0
        self.pons.estimate("ACTION", self.frame)
        # Impact: 1.0 * 10 = 10.0 bps
        # Total: 1.0 (spread) + 10.0 (impact) = 11.0 bps
        self.assertGreaterEqual(self.frame.execution.expected_slippage_bps, 11.0)

    def test_piece_86_slippage_clamp(self):
        """Piece 86: Verify total slippage is clamped to pons_max_slippage_bps."""
        self.frame.standards["pons_max_slippage_bps"] = 20.0
        
        # Setup conditions that would produce > 20 bps
        self.frame.environment.bid_ask_bps = 50.0 # 25 bps half-spread
        self.frame.environment.atr = 5.0 # ~25 bps vol cost
        
        self.pons.estimate("ACTION", self.frame)
        
        # Total should be exactly 20.0
        self.assertEqual(self.frame.execution.expected_slippage_bps, 20.0)

    def test_piece_87_pulse_gate(self):
        """Piece 87: Verify Pons skips evaluation outside ACTION pulse."""
        # 1. SEED pulse
        res_seed = self.pons.estimate("SEED", self.frame)
        self.assertEqual(res_seed["status"], "skipped")
        
        # 2. MINT pulse
        res_mint = self.pons.estimate("MINT", self.frame)
        self.assertEqual(res_mint["status"], "skipped")

if __name__ == "__main__":
    unittest.main()
