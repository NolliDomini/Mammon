import unittest
import pandas as pd
from unittest.mock import MagicMock, patch
from Cerebellum.Soul.orchestrator.service import Orchestrator

class TestSoulHotReloadV4(unittest.TestCase):
    @patch("Hippocampus.Archivist.librarian.librarian.write")
    @patch("Hippocampus.Archivist.librarian.librarian.get_hormonal_vault")
    @patch("Hippocampus.Archivist.librarian.librarian.get_redis_connection")
    def test_piece_150_hot_reload_propagation(self, mock_redis, mock_vault, mock_write):
        """Piece 150: Verify hot-reload propagates new Phase 1 params."""
        # 1. Initial Vault
        vault_v1 = {
            "gold": {"id": "v1", "params": {
                "spread_tight_threshold_bps": 5.0,
                "alloc_equity": 10000.0
            }}
        }
        mock_vault.return_value = vault_v1
        
        orch = Orchestrator()
        self.assertEqual(orch.frame.standards["spread_tight_threshold_bps"], 5.0)
        
        # 2. Update Vault
        vault_v2 = {
            "gold": {"id": "v2", "params": {
                "spread_tight_threshold_bps": 2.5,
                "alloc_equity": 20000.0,
                "soak_window": 24
            }}
        }
        mock_vault.return_value = vault_v2
        
        # 3. Trigger MINT pulse to fire _check_vault_mutation
        df = pd.DataFrame({
            "pulse_type": ["MINT"], "symbol": ["BTC"]
        }, index=[pd.Timestamp.now()])
        
        # We need to ensure Council is mocked but exists in lobes
        orch.lobes["Council"] = MagicMock()
        orch.lobes["Council"].config = {"spread_tight_threshold_bps": 5.0}
        
        # Mock other dependencies to avoid crashes during _process_frame
        orch.lobes["Thalamus"] = MagicMock()
        orch.lobes["Right_Hemisphere"] = MagicMock()
        orch.lobes["Left_Hemisphere"] = MagicMock()
        orch.lobes["Corpus"] = MagicMock()
        orch.lobes["Gatekeeper"] = MagicMock()
        orch.lobes["Brain_Stem"] = MagicMock()
        
        orch._process_frame(df)
        
        # 4. Verify Propagation
        # a. Frame standards updated
        self.assertEqual(orch.frame.standards["spread_tight_threshold_bps"], 2.5)
        self.assertEqual(orch.frame.standards["alloc_equity"], 20000.0)
        self.assertEqual(orch.frame.standards["soak_window"], 24)
        
        # b. Lobe config updated
        self.assertEqual(orch.lobes["Council"].config["spread_tight_threshold_bps"], 2.5)
        
        print("[TEST] Hot-Reload Propagation Verified (Phase 1 + Evolution).")

if __name__ == "__main__":
    unittest.main()
