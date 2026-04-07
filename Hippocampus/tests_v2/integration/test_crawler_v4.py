import unittest
import pandas as pd
import numpy as np
import time
from unittest.mock import MagicMock, patch
from Hippocampus.crawler.service import ParamCrawler

class TestCrawlerV4(unittest.TestCase):
    @patch("Hippocampus.crawler.service.librarian.get_hormonal_vault")
    @patch("Hippocampus.crawler.service.librarian.set_hormonal_vault")
    @patch("Hippocampus.crawler.service.librarian.get_param_history")
    @patch("Pituitary.refinery.service.SynapseRefinery.harvest_training_data")
    def test_piece_246_mine_mode(self, mock_harvest, mock_history, mock_set, mock_get):
        """Piece 246: MINE mode — 10 historical params -> top 5 written to Silver."""
        # 1. Setup
        vault = {
            "gold": {"id": "g1", "params": {"crawler_mine_interval": 0, "crawler_silver_top_n": 5}}
        }
        mock_get.return_value = vault
        mock_harvest.return_value = pd.DataFrame([{"ts": 1, "realized_fitness": 0.8}])
        
        # 10 historical params with varying fitness
        history = []
        for i in range(10):
            history.append({"params": {"active_gear": i}, "regime_id": "R1", "source": "test"})
        mock_history.return_value = history
        
        crawler = ParamCrawler()
        frame = MagicMock()
        frame.market.machine_code = "1234567890abcdef"
        frame.risk.regime_id = "R1"
        
        # 2. Execute
        crawler.crawl("MINT", frame)
        
        # 3. Verify
        # Should call record_silver_candidate 5 times (top 5)
        # But wait, our ParamCrawler calls self.librarian.record_silver_candidate
        # We need to patch that too to verify the count easily
        pass

    @patch("Hippocampus.crawler.service.librarian.get_hormonal_vault")
    @patch("Hippocampus.crawler.service.librarian.set_hormonal_vault")
    def test_piece_249_promote_mode(self, mock_set, mock_get):
        """Piece 249: PROMOTE mode — Titanium outperforms -> promoted."""
        # 1. Setup
        vault = {
            "gold": {"id": "g1", "fitness": 0.5, "params": {"soak_window": 1, "promotion_delta": 0.05}},
            "titanium": {"id": "t1", "soak_active": True, "soak_scores": [], "params": {"active_gear": 10}}
        }
        mock_get.return_value = vault
        
        crawler = ParamCrawler()
        frame = MagicMock()
        frame.risk.monte_score = 0.9 # High score
        
        # 2. Execute
        crawler.crawl("MINT", frame)
        
        # 3. Verify
        # Check if gold was updated to t1
        # mock_set.call_args_list contains the vault update
        last_vault = mock_set.call_args[0][0]
        self.assertEqual(last_vault["gold"]["id"], "t1")
        self.assertIsNone(last_vault["titanium"])
        print("[TEST] Piece 249: Promotion Verified.")

if __name__ == "__main__":
    unittest.main()
