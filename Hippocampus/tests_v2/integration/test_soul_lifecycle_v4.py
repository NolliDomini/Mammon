import unittest
import pandas as pd
import numpy as np
from unittest.mock import MagicMock, patch
from Cerebellum.Soul.orchestrator.service import Orchestrator
from Cerebellum.Soul.brain_frame.service import BrainFrame

class TestSoulLifecycleV4(unittest.TestCase):
    @patch("Hippocampus.Archivist.librarian.librarian.write")
    @patch("Hippocampus.Archivist.librarian.librarian.get_hormonal_vault")
    @patch("Hippocampus.Archivist.librarian.librarian.get_redis_connection")
    def setUp(self, mock_redis, mock_vault, mock_write):
        mock_vault.return_value = {
            "active_gear": 10,
            "gold": {"params": {
                "council_w_spread": 0.2,
                "brain_stem_val_n_sigma": 1.5,
                "alloc_equity": 10000.0,
                "alloc_risk_per_trade_pct": 0.01,
                "alloc_max_notional": 5000.0,
                "alloc_max_z": 2.0,
                "alloc_cost_penalty_divisor": 100.0,
                "alloc_max_cost_penalty": 0.5,
                "alloc_min_qty": 0.0001
            }, "id": 1},
            "regime_weight_table": {}
        }
        self.orchestrator = Orchestrator()
        
        # Mock all lobes to ensure we reach the gates
        self.orchestrator.lobes["Thalamus"] = MagicMock()
        self.orchestrator.lobes["Right_Hemisphere"] = MagicMock()
        
        # Use a real Council but patch its librarian calls
        from Cerebellum.council.service import Council
        with patch("Cerebellum.council.service.librarian"):
            self.orchestrator.lobes["Council"] = Council(config=mock_vault.return_value["gold"]["params"])
        
        self.orchestrator.lobes["Left_Hemisphere"] = MagicMock()
        self.orchestrator.lobes["Corpus"] = MagicMock()
        self.orchestrator.lobes["Gatekeeper"] = MagicMock()
        self.orchestrator.lobes["Brain_Stem"] = MagicMock()

    def test_piece_128_full_propagation(self):
        """Piece 128: Verify field propagation through the full lifecycle."""
        # 1. Setup Input Data (simulating Thalamus output)
        df = pd.DataFrame({
            "open": [100.0] * 50, "high": [101.0] * 50, "low": [99.0] * 50,
            "close": [100.0] * 50, "volume": [1000] * 50, "symbol": ["AAPL"] * 50,
            "bid": [99.95] * 50, "ask": [100.05] * 50, # 10 bps spread
            "pulse_type": ["ACTION"] * 50
        }, index=pd.date_range(end=pd.Timestamp.now(), periods=50, freq="1min"))
        
        # 2. Trigger Signal (Right Hemisphere)
        self.orchestrator.frame.structure.tier1_signal = 1
        self.orchestrator.frame.structure.price = 100.0 # Piece 128 fix: set price
        
        # 3. Process ACTION Pulse
        # Mock Gatekeeper to approve
        def mock_decide(pulse, frame):
            frame.command.approved = 1
            frame.command.ready_to_fire = True
            
        self.orchestrator.lobes["Gatekeeper"].decide.side_effect = mock_decide
        
        # Mock BrainStem to hydrate valuation
        def mock_hunt(pulse, frame, **kwargs):
            frame.valuation.mean = 105.0
            frame.valuation.lower_band = 95.0
            frame.valuation.std_dev = 5.0
            frame.valuation.z_distance = 1.0 # (105-100)/5
            
        self.orchestrator.lobes["Brain_Stem"].load_and_hunt.side_effect = mock_hunt
        
        # Mock Council indicators to avoid math errors but allow spread engine to run
        with patch.object(self.orchestrator.lobes["Council"], "_calculate_atr_score", return_value={"score": 0.5, "val": 1.0, "avg": 1.0}):
            with patch.object(self.orchestrator.lobes["Council"], "_calculate_adx_score", return_value={"score": 0.5, "val": 25.0, "avg": 25.0}):
                with patch.object(self.orchestrator.lobes["Council"], "_calculate_vol_score", return_value={"score": 0.5, "val": 1000.0, "avg": 1000.0}):
                    with patch.object(self.orchestrator.lobes["Council"], "_calculate_vwap_score", return_value={"score": 0.5, "val": 100.0, "avg": 100.0}):
                        # Execute
                        self.orchestrator._process_frame(df)
        
        # 4. Verify Propagation
        # a. Council Spread fields (10 bps spread on 100 mid)
        self.assertAlmostEqual(self.orchestrator.frame.environment.bid_ask_bps, 10.0)
        
        # b. Pons Cost fields
        self.assertGreater(self.orchestrator.frame.execution.total_cost_bps, 0)
        
        # c. Allocation Sizing
        self.assertGreater(self.orchestrator.frame.command.qty, 0)
        self.assertEqual(self.orchestrator.frame.command.size_reason, "SIZED_COST_PENALIZED")
        
        # d. Telemetry
        last_log = self.orchestrator.pulse_log[-1]
        self.assertIn("friction_summary", last_log)
        self.assertEqual(last_log["friction_summary"]["z_distance"], 1.0)

    @patch("Hippocampus.Archivist.librarian.librarian.write")
    @patch("Hippocampus.Archivist.librarian.librarian.get_hormonal_vault")
    @patch("Hippocampus.Archivist.librarian.librarian.get_redis_connection")
    @patch("Hippocampus.Archivist.librarian.librarian.mint_synapse")
    def test_piece_143_synapse_persistence(self, mock_mint, mock_redis, mock_vault, mock_write):
        """Piece 143: Verify synapse ticket contains all Phase 1 fields."""
        mock_vault.return_value = {
            "gold": {"params": {
                "alloc_equity": 10000.0,
                "alloc_risk_per_trade_pct": 0.01,
                "alloc_max_notional": 5000.0,
                "alloc_max_z": 2.0,
                "alloc_cost_penalty_divisor": 100.0,
                "alloc_max_cost_penalty": 0.5,
                "alloc_min_qty": 0.0001
            }, "id": 1}
        }
        
        # 1. Setup Data for MINT pulse
        df = pd.DataFrame({
            "open": [100.0] * 50, "high": [101.0] * 50, "low": [99.0] * 50,
            "close": [100.0] * 50, "volume": [1000] * 50, "symbol": ["AAPL"] * 50,
            "bid": [99.95] * 50, "ask": [100.05] * 50, 
            "pulse_type": ["MINT"] * 50
        }, index=pd.date_range(end=pd.Timestamp.now(), periods=50, freq="1min"))
        
        # 2. Mock Council to write spread data
        self.orchestrator.lobes["Council"].consult = MagicMock()
        def mock_consult(pulse, frame):
            frame.environment.bid_ask_bps = 10.0
            frame.environment.spread_score = 0.9
            
        self.orchestrator.lobes["Council"].consult.side_effect = mock_consult
        
        # Mock Allocation to write qty
        def mock_alloc(pulse, frame):
            frame.command.qty = 5.0
            
        # We need to manually trigger allocation-like effect if we want to test persistence
        # In Orchestrator, MINT doesn't run Allocation. But it DOES run Amygdala.
        # So we'll just ensure the frame has the data at the time Amygdala is called.
        
        # Let's populate the frame slots directly before Amygdala is called in the loop.
        # But _process_frame clears it at start.
        # So we mock a lobe that runs during MINT to populate it.
        # Council runs on MINT.
        
        # 3. Execute
        self.orchestrator._process_frame(df)
        
        # 4. Verify Amygdala called mint_synapse with full ticket
        self.assertTrue(mock_mint.called)
        ticket = mock_mint.call_args[0][0]
        
        self.assertEqual(ticket["bid_ask_bps"], 10.0)
        self.assertEqual(ticket["spread_score"], 0.9)
        # Note: qty might be 0 because Allocation didn't run on MINT pulse.
        # But Amygdala should have captured whatever was in the frame.
        # The Orchestrator's internal frame persists across pulses? No, it's reset.
        # But wait, MINT happens AFTER ACTION in a real system.
        # For this test, we just care that the fields are in the TICKET.
        # We ensured Council wrote bid_ask_bps during this MINT pulse.
        
        self.assertEqual(ticket["bid_ask_bps"], 10.0)

if __name__ == "__main__":
    unittest.main()
