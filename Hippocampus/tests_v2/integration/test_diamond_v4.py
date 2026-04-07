import unittest
import pandas as pd
import numpy as np
from unittest.mock import MagicMock, patch
from Pituitary.search.diamond import DiamondGland
from Hospital.Optimizer_loop.optimizer_v2.service import PARAM_KEYS

class TestDiamondV4(unittest.TestCase):
    @patch("Pituitary.search.diamond.librarian.get_hormonal_vault")
    @patch("Pituitary.search.diamond.librarian.set_hormonal_vault")
    @patch("Pituitary.refinery.service.SynapseRefinery.harvest_training_data")
    def test_piece_261_diamond_titanium_synthesis(self, mock_harvest, mock_set, mock_get):
        """Piece 261: Diamond produces valid Titanium with all 46 params."""
        # 1. Setup
        mock_get.return_value = {"gold": {"params": {}}, "silver": []}
        
        # 50 random rows of training data
        data = pd.DataFrame(np.random.rand(50, len(PARAM_KEYS)), columns=PARAM_KEYS)
        data["realized_fitness"] = np.random.rand(50)
        mock_harvest.return_value = data
        
        diamond = DiamondGland()
        
        # 2. Execute
        diamond.perform_deep_search(hours=1)
        
        # 3. Verify
        # Should call set_hormonal_vault with titanium
        # last call should have titanium entry
        last_vault = mock_set.call_args[0][0]
        self.assertIn("titanium", last_vault)
        self.assertTrue(last_vault["titanium"]["soak_active"])
        self.assertEqual(len(last_vault["titanium"]["params"]), 47)
        
        # 4. Verify Rails (Piece 262)
        self.assertIn("diamond_rails", last_vault)
        bounds = last_vault["diamond_rails"]["bounds"]
        for key in PARAM_KEYS:
            self.assertIn(key, bounds)
            self.assertLessEqual(bounds[key]["min"], bounds[key]["max"])
            
        print("[TEST] Piece 261 & 262: Diamond ML Synthesis Verified. 47 params covered.")

if __name__ == "__main__":
    unittest.main()
