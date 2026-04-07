import unittest
import pandas as pd
import numpy as np
from unittest.mock import MagicMock, patch
from Brain_Stem.trigger.service import Trigger
from Cerebellum.Soul.brain_frame.service import BrainFrame

class TestTriggerValuationSurface(unittest.TestCase):
    @patch("Brain_Stem.trigger.service.Trigger._verify_credentials")
    @patch("Hippocampus.Archivist.librarian.librarian.get_hormonal_vault")
    @patch("Hippocampus.Archivist.librarian.librarian.get_redis_connection")
    def setUp(self, mock_redis, mock_vault, mock_verify):
        mock_vault.return_value = {"gold": {"params": {}, "id": 1}}
        # Mocking treasury to avoid DB errors
        with patch("Medulla.treasury.gland.TreasuryGland.__init__", return_value=None):
            self.trigger = Trigger(api_key="fake", api_secret="fake")
            self.trigger.treasury = MagicMock()
            from Brain_Stem.pons_execution_cost import PonsExecutionCost
            self.trigger.pons = MagicMock(spec=PonsExecutionCost)
            
        self.frame = BrainFrame()
        self.frame.market.ohlcv = pd.DataFrame({"close": [100.0] * 50})
        self.frame.structure.price = 100.0
        # Ensure policy allows firing check
        self.frame.command.ready_to_fire = True
        self.frame.command.approved = 1
        self.frame.command.qty = 1.0 # Piece 91 fix: ensure qty > 0
        self.frame.market.symbol = "AAPL"
        self.frame.market.execution_mode = "DRY_RUN"

    def test_piece_91_valuation_fields_populated(self):
        """Piece 91: Verify ValuationSlot hydration."""
        # Mock valuation gate to return known values
        mock_val = {
            "mean": 105.0,
            "sigma": 2.0,
            "upper": 108.0,
            "lower": 102.0
        }
        
        with patch.object(self.trigger, "_run_valuation_gate", return_value=mock_val):
            with patch.object(self.trigger, "_run_risk_gate", return_value=0.9):
                print(f"DEBUG: Before hunt, mean={self.frame.valuation.mean}")
                self.trigger.load_and_hunt("ACTION", self.frame)
                print(f"DEBUG: After hunt, mean={self.frame.valuation.mean}, exit_reason={self.trigger.last_exit_reason}")
        
        v = self.frame.valuation
        self.assertEqual(v.mean, 105.0)
        self.assertEqual(v.std_dev, 2.0)
        self.assertEqual(v.upper_band, 108.0)
        self.assertEqual(v.lower_band, 102.0)
        self.assertEqual(v.valuation_source, "TRIGGER_GATE")
        # z_distance = (105.0 - 100.0) / 2.0 = 2.5
        self.assertEqual(v.z_distance, 2.5)

    def test_piece_92_zero_std_dev_handling(self):
        """Piece 92: Verify z_distance is 0.0 when std_dev is 0."""
        mock_val = {
            "mean": 100.0,
            "sigma": 0.0, # Zero std_dev
            "upper": 100.0,
            "lower": 100.0
        }
        
        with patch.object(self.trigger, "_run_valuation_gate", return_value=mock_val):
            with patch.object(self.trigger, "_run_risk_gate", return_value=0.9):
                self.trigger.load_and_hunt("ACTION", self.frame)
        
        self.assertEqual(self.frame.valuation.z_distance, 0.0)

if __name__ == "__main__":
    unittest.main()
