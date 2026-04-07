import unittest
import pandas as pd
from Cerebellum.council.spread_engine.service import SpreadEngine
from Cerebellum.Soul.brain_frame.service import BrainFrame

class TestSpreadEngineContract(unittest.TestCase):
    def setUp(self):
        self.engine = SpreadEngine()
        self.frame = BrainFrame()
        # Mock standards
        self.frame.standards = {
            "spread_atr_ratio": 0.10,
            "spread_score_scalar": 1.0,
            "spread_regime_tight_bps": 2.0,
            "spread_regime_normal_bps": 5.0,
            "spread_regime_wide_bps": 15.0
        }
        # Set ATR
        self.frame.environment.atr = 1.0

    def test_piece_60_happy_path(self):
        """Piece 60: Valid bid/ask -> correct bps, score, regime."""
        df = pd.DataFrame({
            "close": [100.0],
            "symbol": ["AAPL"],
            "bid": [99.98], # 2 bps spread
            "ask": [100.02]
        })
        self.frame.market.ohlcv = df
        
        res = self.engine.evaluate("ACTION", self.frame)
        
        # 1. BPS Calculation: ((100.02 - 99.98) / 100.0) * 10000 = 4 bps
        self.assertAlmostEqual(self.frame.environment.bid_ask_bps, 4.0)
        
        # 2. Score Calculation:
        # ATR_bps = (1.0 / 100.0) * 10000 = 100 bps
        # Ratio = 4 / (100 * 1.0) = 0.04
        # Score = 1.0 - 0.04 = 0.96
        self.assertAlmostEqual(self.frame.environment.spread_score, 0.96)
        
        # 3. Regime: 4.0 <= 5.0 (Normal)
        self.assertEqual(self.frame.environment.spread_regime, "NORMAL")
        self.assertEqual(res["status"], "live_quote")

    def test_piece_61_invalid_quote_fallback(self):
        """Piece 61: Invalid quote -> MNER, ATR fallback."""
        df = pd.DataFrame({
            "close": [100.0],
            "symbol": ["AAPL"],
            "bid": [100.5], # Invalid: bid > ask
            "ask": [100.0]
        })
        self.frame.market.ohlcv = df
        
        # Capture stdout to verify MNER log
        import io
        from contextlib import redirect_stdout
        f = io.StringIO()
        with redirect_stdout(f):
            res = self.engine.evaluate("ACTION", self.frame)
            
        output = f.getvalue()
        self.assertIn("COUNCIL-E-SPR-701", output)
        self.assertEqual(res["status"], "atr_fallback:invalid_quote")
        
        # Expected ATR Fallback BPS:
        # ATR_bps = (1.0 / 100.0) * 10000 = 100 bps
        # Estimated_spread = 100 * 0.10 = 10 bps
        self.assertAlmostEqual(self.frame.environment.bid_ask_bps, 10.0)

    def test_piece_62_missing_columns_fallback(self):
        """Piece 62: Missing bid/ask columns -> ATR fallback."""
        # DataFrame without bid/ask
        df = pd.DataFrame({
            "close": [100.0],
            "symbol": ["AAPL"]
        })
        self.frame.market.ohlcv = df
        
        import io
        from contextlib import redirect_stdout
        f = io.StringIO()
        with redirect_stdout(f):
            res = self.engine.evaluate("ACTION", self.frame)
            
        output = f.getvalue()
        self.assertIn("COUNCIL-E-SPR-702", output)
        self.assertEqual(res["status"], "atr_fallback:missing_inputs")
        self.assertAlmostEqual(self.frame.environment.bid_ask_bps, 10.0)

    def test_piece_63_regime_boundaries(self):
        """Piece 63: Verify regime transitions based on bps."""
        # Thresholds: Tight=2, Normal=5, Wide=15
        
        # 1. TIGHT: 1 bps
        df = pd.DataFrame({"close": [100.0], "symbol": ["A"], "bid": [99.995], "ask": [100.005]})
        self.frame.market.ohlcv = df
        self.engine.evaluate("ACTION", self.frame)
        self.assertEqual(self.frame.environment.spread_regime, "TIGHT")
        
        # 2. NORMAL: 4 bps
        df = pd.DataFrame({"close": [100.0], "symbol": ["A"], "bid": [99.98], "ask": [100.02]})
        self.frame.market.ohlcv = df
        self.engine.evaluate("ACTION", self.frame)
        self.assertEqual(self.frame.environment.spread_regime, "NORMAL")
        
        # 3. WIDE: 10 bps
        df = pd.DataFrame({"close": [100.0], "symbol": ["A"], "bid": [99.95], "ask": [100.05]})
        self.frame.market.ohlcv = df
        self.engine.evaluate("ACTION", self.frame)
        self.assertEqual(self.frame.environment.spread_regime, "WIDE")
        
        # 4. STRESSED: 20 bps
        df = pd.DataFrame({"close": [100.0], "symbol": ["A"], "bid": [99.90], "ask": [100.10]})
        self.frame.market.ohlcv = df
        self.engine.evaluate("ACTION", self.frame)
        self.assertEqual(self.frame.environment.spread_regime, "STRESSED")

    def test_piece_66_pulse_gate(self):
        """Piece 66: Verify SpreadEngine skips evaluation on MINT pulse."""
        res = self.engine.evaluate("MINT", self.frame)
        self.assertEqual(res["status"], "skipped")
        self.assertEqual(res["reason"], "pulse_gate")

if __name__ == "__main__":
    unittest.main()
