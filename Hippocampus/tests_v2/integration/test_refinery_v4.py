import unittest
import pandas as pd
import numpy as np
from unittest.mock import MagicMock, patch
from Pituitary.refinery.service import SynapseRefinery
from Hospital.Optimizer_loop.optimizer_v2.service import PARAM_KEYS

class TestRefineryV4(unittest.TestCase):
    @patch("Pituitary.refinery.service.librarian.read")
    def test_piece_222_column_expansion(self, mock_read):
        """Piece 222: SynapseRefinery produces 46 columns even if synapse DB only has 23."""
        # 1. Mock synapse rows with only 23 columns
        # We'll create a dict for each row to simulate DataFrame construction from rows
        mock_row = {"ts": 12345, "symbol": "BTC", "pulse_type": "MINT", "tier_score": 0.8}
        # Add 23 legacy params
        for i in range(23):
            mock_row[PARAM_KEYS[i]] = 0.5
            
        mock_read.side_effect = [
            [mock_row], # Synapse rows
            []          # PnL rows
        ]
        
        refinery = SynapseRefinery()
        df = refinery.harvest_training_data(hours=1)
        
        # 2. Verify all 46 keys are present
        for key in PARAM_KEYS:
            self.assertIn(key, df.columns, f"Missing key {key} in refined DataFrame")
            
        # 3. Verify missing ones are filled with defaults
        # Index 24 is spread_tight_threshold_bps (New in V4)
        self.assertAlmostEqual(df.iloc[0]["spread_tight_threshold_bps"], 25.05, places=1) # Median of [0.1, 50.0]
        
        print(f"[TEST] Piece 222: Refinery column expansion verified. Produced {len(df.columns)} columns.")

if __name__ == "__main__":
    unittest.main()
