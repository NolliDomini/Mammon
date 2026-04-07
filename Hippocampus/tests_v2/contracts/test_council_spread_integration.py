import unittest
import pandas as pd
import numpy as np
from unittest.mock import MagicMock, patch
from Cerebellum.council.service import Council
from Cerebellum.Soul.brain_frame.service import BrainFrame

class TestCouncilSpreadIntegration(unittest.TestCase):
    @patch("Hippocampus.Archivist.librarian.librarian.write")
    @patch("Hippocampus.Archivist.librarian.librarian.get_hormonal_vault")
    def test_piece_64_spread_weighted_confidence(self, mock_vault, mock_write):
        """Piece 64: Verify spread_score is weighted into Council confidence."""
        mock_vault.return_value = {"regime_weight_table": {}}
        
        # 1. Setup config with weights
        config = {
            "council_w_atr": 0.0,
            "council_w_adx": 0.0,
            "council_w_vol": 0.0,
            "council_w_vwap": 0.0,
            "council_w_spread": 1.0 # 100% weight on spread for this test
        }
        council = Council(config=config)
        
        # 2. Setup frame with data that produces a specific spread score
        frame = BrainFrame()
        frame.standards = {"spread_atr_ratio": 0.1, "spread_score_scalar": 1.0}
        frame.environment.atr = 1.0
        
        df = pd.DataFrame({
            "open": [100.0, 100.0], "high": [101.0, 101.0], "low": [99.0, 99.0], 
            "close": [100.0, 100.0], "volume": [1000, 1000], "symbol": ["AAPL", "AAPL"],
            "bid": [99.95, 99.95], "ask": [100.05, 100.05] # 10 bps spread
        })
        frame.market.ohlcv = df
        
        # 3. Consult
        # Council internally calls SpreadEngine.evaluate, which writes to frame.environment.spread_score
        council.consult("ACTION", frame)
        
        # Expected Spread Score:
        # bps = (0.10 / 100.0) * 10000 = 10 bps
        # atr_bps = (1.0 / 100.0) * 10000 = 100 bps
        # Ratio = 10 / (100 * 1.0) = 0.1
        # Score = 1.0 - 0.1 = 0.90
        
        self.assertAlmostEqual(frame.environment.spread_score, 0.90)
        
        # Since weight is 1.0 for spread and 0.0 for others, confidence should be 0.90
        self.assertAlmostEqual(frame.environment.confidence, 0.90)

    @patch("Hippocampus.Archivist.librarian.librarian.write")
    @patch("Hippocampus.Archivist.librarian.librarian.get_hormonal_vault")
    def test_piece_65_gold_param_overrides(self, mock_vault, mock_write):
        """Piece 65: Verify Gold param overrides for spread weight are respected."""
        # 1. Setup vault with a specific override for a regime
        mock_vault.return_value = {
            "regime_weight_table": {
                "D2_A3_V2_T0": { 
                    "w_atr": 0.5, "w_adx": 0.0, "w_vol": 0.0, "w_vwap": 0.0,
                    "w_spread": 0.5,
                    "trace": "D2_BALANCED"
                }
            }
        }
        
        # 2. Setup Council with default weights (which should be overridden)
        config = {"council_w_spread": 1.0}
        council = Council(config=config)
        
        # 3. Setup frame with data triggering D2 regime
        frame = BrainFrame()
        frame.standards = {"spread_atr_ratio": 0.1, "spread_score_scalar": 1.0}
        frame.environment.atr = 1.0
        
        # Price 100, Mid 100, Dist 0. Close >> VWAP (to trigger D2)
        # Use 50 bars to satisfy avg_window
        df = pd.DataFrame({
            "open": [100.0] * 50, "high": [101.0] * 50, "low": [99.0] * 50, 
            "close": [100.0] * 50, "volume": [1000] * 50, "symbol": ["AAPL"] * 50,
            "bid": [99.95] * 50, "ask": [100.05] * 50 # 10 bps spread -> score 0.9
        }, index=pd.date_range(end=pd.Timestamp.now(), periods=50, freq="1min"))
        frame.market.ohlcv = df
        
        # 4. Consult
        # Instead of fighting Numba kernels, we mock the internal score calculators 
        # to guarantee the inputs to the weighted average.
        
        with patch.object(council, "_calculate_atr_score", return_value={"score": 0.5, "val": 1.0, "avg": 1.0}):
            with patch.object(council, "_calculate_adx_score", return_value={"score": 0.0, "val": 0.0, "avg": 0.0}):
                with patch.object(council, "_calculate_vol_score", return_value={"score": 0.0, "val": 0.0, "avg": 0.0}):
                    with patch.object(council, "_calculate_vwap_score", return_value={"score": 0.0, "val": 0.0, "avg": 0.0}):
                        
                        # Use the exact regime ID that the council will generate based on mocks
                        mock_vault.return_value["regime_weight_table"]["D0_A2_V0_T0"] = {
                            "w_atr": 0.5, "w_adx": 0.0, "w_vol": 0.0, "w_vwap": 0.0,
                            "w_spread": 0.5,
                            "trace": "D2_BALANCED"
                        }
                        
                        # SpreadEngine.evaluate returns 0.90 based on setup
                        council.consult("ACTION", frame)
                        print(f"DEBUG: Generated Regime ID: {frame.risk.regime_id}")
                        
                        # Expected: (ATR_score 0.5 * 0.5) + (Spread_score 0.9 * 0.5) / (0.5 + 0.5)
                        # = 0.25 + 0.45 = 0.70
                        self.assertAlmostEqual(frame.environment.confidence, 0.70)

if __name__ == "__main__":
    unittest.main()
