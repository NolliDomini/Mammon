import unittest
import pandas as pd
import numpy as np
from unittest.mock import MagicMock, patch
from Hippocampus.fornix.service import Fornix
from Hippocampus.duck_pond.service import DuckPond
from pathlib import Path
import os

class TestFornixV4Compatibility(unittest.TestCase):
    def setUp(self):
        self.test_db = "test_fornix.duckdb"
        if os.path.exists(self.test_db):
            os.remove(self.test_db)
        
        self.pond = DuckPond(db_path=self.test_db)
        csv_path = Path(__file__).parent / "dummy_bars.csv"
        self.pond.ingest_csv(str(csv_path))

    def tearDown(self):
        self.pond.close()
        if os.path.exists(self.test_db):
            os.remove(self.test_db)

    @patch("Hippocampus.Archivist.librarian.librarian.get_hormonal_vault")
    @patch("Hippocampus.Archivist.librarian.librarian.get_redis_connection")
    def test_piece_147_replay_compatibility(self, mock_redis, mock_vault):
        """Piece 147: Verify Fornix replays data with new BrainFrame fields."""
        mock_vault.return_value = {
            "gold": {"params": {
                "active_gear": 5,
                "alloc_min_qty": 0.0001
            }, "id": 1}
        }
        
        # Initialize Fornix with small config
        config = {
            "monte_scale": 0.25,
            "paths_per_lane": 100,
            "risk_gate_paths_per_lane": 10,
            "valuation_paths": 100,
            "chunk_size": 2,
            "max_hours": 1,
            "checkpoint_interval": 10,
            "optimizer_interval_bars": 75,
        }
        
        # We need to mock some internal components because they might fail without real data/connections
        # but we want to see the Soul lifecycle run.
        
        with patch("Hippocampus.fornix.service.DiamondGland"):
            fornix = Fornix(test_pulse=config, db_path=self.test_db)
            
            # Run replay
            fornix.run(symbols=["BTC"], resume=False)
            
            # Verify output in history_synapse
            synapses = self.pond.conn.execute("SELECT * FROM history_synapse").df()
            
            # Should have at least one MINT (dummy has 6 bars, SmartGland defaults to 5m windows)
            # Actually, dummy has 6 bars, so it should mint at least once.
            self.assertGreater(len(synapses), 0)
            
            # Verify new columns exist and are populated (even if 0.0)
            self.assertIn("bid_ask_bps", synapses.columns)
            self.assertIn("val_mean", synapses.columns)
            self.assertIn("exec_total_cost_bps", synapses.columns)
            self.assertIn("qty", synapses.columns)
            
            print(f"[TEST] Fornix Replay Success. Synapses: {len(synapses)}")

if __name__ == "__main__":
    unittest.main()
