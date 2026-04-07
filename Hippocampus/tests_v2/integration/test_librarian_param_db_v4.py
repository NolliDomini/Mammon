import unittest
from Hippocampus.Archivist.librarian import MultiTransportLibrarian
from pathlib import Path
import os
import json
from unittest.mock import patch, MagicMock

class TestLibrarianParamDBV4(unittest.TestCase):
    def setUp(self):
        self.test_db = "test_params.duckdb"
        if os.path.exists(self.test_db):
            os.remove(self.test_db)
        
        # We need to bypass singleton for testing
        self.lib = MultiTransportLibrarian.__new__(MultiTransportLibrarian)
        self.lib._duck_conn = None
        self.lib._param_conn = None
        self.lib._redis_conn = MagicMock() # Mock redis
        
        self.lib.root_path = Path(__file__).resolve().parents[3]
        self.lib.data_path = self.lib.root_path / "Hippocampus" / "data"
        self.lib.param_db_path = Path(self.test_db)
        self.lib.duck_db_path = Path("test_synapse.duckdb")
        
        self.lib._setup_param_tables()

    def tearDown(self):
        if self.lib._param_conn:
            self.lib._param_conn.close()
        if os.path.exists(self.test_db):
            os.remove(self.test_db)
        if os.path.exists("test_synapse.duckdb"):
            os.remove("test_synapse.duckdb")

    def test_piece_195_crud_lifecycle(self):
        """Piece 195: Verify full CRUD for param_sets."""
        params = {"active_gear": 5, "stop_loss_mult": 1.5}
        
        # 1. Install Gold
        self.lib.install_gold_params(params, 0.85, "manual")
        
        # 2. Record Platinum
        self.lib.record_param_set("plat_1", "PLATINUM", params, "D2_A1_V1_T1", 0.92, "VolumeFurnace")
        
        # 3. Record Silver
        self.lib.record_param_set("silv_1", "SILVER", params, "D2_A1_V1_T1", 0.78, "Crawler")
        
        # 4. Query History
        history = self.lib.get_param_history(tier="GOLD")
        self.assertEqual(len(history), 1)
        self.assertEqual(history[0]["fitness"], 0.85)
        
        history_plat = self.lib.get_param_history(tier="PLATINUM")
        self.assertEqual(len(history_plat), 1)
        self.assertEqual(history_plat[0]["id"], "plat_1")
        
        # 5. Demote to Bronze
        self.lib.demote_to_bronze("plat_1")
        
        history_bronze = self.lib.get_param_history(tier="BRONZE")
        self.assertEqual(len(history_bronze), 1)
        self.assertEqual(history_bronze[0]["id"], "plat_1")
        self.assertIsNotNone(history_bronze[0]["active_to"])
        
        print("[TEST] Librarian Param DB CRUD Verified.")

if __name__ == "__main__":
    unittest.main()
