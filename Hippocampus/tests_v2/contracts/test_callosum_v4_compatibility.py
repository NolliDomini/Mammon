import unittest
import pandas as pd
from unittest.mock import MagicMock, patch
from Corpus.callosum.service import Callosum
from Cerebellum.Soul.brain_frame.service import BrainFrame

class TestCallosumV4Compatibility(unittest.TestCase):
    @patch("Corpus.callosum.service.librarian.write")
    @patch("Corpus.callosum.service.librarian.get_hormonal_vault")
    def test_piece_119_callosum_compatibility(self, mock_vault, mock_write):
        """Piece 119: Callosum must produce valid tier_score with v4 slots."""
        mock_vault.return_value = {"regime_weight_table": {}}
        
        callosum = Callosum(config={"callosum_w_monte": 0.5, "callosum_w_right": 0.5})
        
        frame = BrainFrame()
        # Populate new slots to test "interference"
        frame.environment.bid_ask_bps = 10.0
        frame.valuation.mean = 105.0
        frame.execution.total_cost_bps = 25.0
        
        # Populate inputs Callosum actually uses
        frame.risk.monte_score = 0.8
        frame.structure.tier1_signal = 1
        
        # Calculate
        callosum.score_tier("ACTION", frame)
        
        # Expected: (0.8 * 0.5) + (1.0 * 0.5) = 0.4 + 0.5 = 0.9
        self.assertAlmostEqual(frame.risk.tier_score, 0.9)

if __name__ == "__main__":
    unittest.main()
