import unittest
import pandas as pd
from unittest.mock import MagicMock, patch
from Thalamus.relay.service import Thalamus
from Cerebellum.Soul.orchestrator.service import Orchestrator

class TestThalamusBidAskIntegration(unittest.IsolatedAsyncioTestCase):
    @patch("Hippocampus.Archivist.librarian.librarian.get_hormonal_vault")
    @patch("Hippocampus.Archivist.librarian.librarian.get_redis_connection")
    def setUp(self, mock_redis, mock_vault):
        mock_vault.return_value = {
            "active_gear": 10,
            "gold": {"params": {}, "id": 1}
        } 
        self.orchestrator = Orchestrator()
        # Provide fake keys to satisfy the client initialization check
        self.thalamus = Thalamus(api_key="fake", api_secret="fake", optical_tract=self.orchestrator)
        
    @patch("Thalamus.relay.service.Thalamus.get_snapshot")
    @patch("Thalamus.relay.service.Thalamus._pulse_from_alpaca")
    @patch("Hippocampus.Archivist.librarian.librarian.get_hormonal_vault")
    @patch("Hippocampus.Archivist.librarian.librarian.get_redis_connection")
    async def test_piece_16_bid_ask_reached_soul(self, mock_redis, mock_vault, mock_alpaca, mock_snapshot):
        """Piece 16: Verify bid/ask columns exist when snapshot succeeds."""
        mock_vault.return_value = {
            "active_gear": 10,
            "gold": {"params": {}, "id": 1}
        } 
        # Mock historical bars
        df_mock = pd.DataFrame({
            "ts": [pd.Timestamp.now()],
            "open": [100.0], "high": [105.0], "low": [95.0], "close": [102.0], "volume": [1000],
            "symbol": ["AAPL"]
        }).set_index("ts")
        mock_alpaca.return_value = df_mock
        
        # Mock Alpaca Snapshot response
        class MockQuote:
            bid_price = 101.5
            ask_price = 102.5
            bid_size = 10
            ask_size = 10

        class MockSnapshot:
            latest_quote = MockQuote()
            
        mock_snapshot.return_value = {"AAPL": MockSnapshot()}
        
        # Capture the frame at Soul
        captured_df = []
        def mock_process(data):
            captured_df.append(data)
            
        with patch.object(self.orchestrator, "_process_frame", side_effect=mock_process):
            self.thalamus.pulse(symbols=["AAPL"], pulse_type="SEED")
            
        self.assertTrue(len(captured_df) > 0)
        df = captured_df[0]
        self.assertIn("bid", df.columns)
        self.assertIn("ask", df.columns)
        self.assertEqual(df["bid"].iloc[0], 101.5)
        self.assertEqual(df["ask"].iloc[0], 102.5)

    @patch("Thalamus.relay.service.Thalamus.get_snapshot")
    @patch("Thalamus.relay.service.Thalamus._pulse_from_alpaca")
    @patch("Hippocampus.Archivist.librarian.librarian.get_hormonal_vault")
    @patch("Hippocampus.Archivist.librarian.librarian.get_redis_connection")
    async def test_piece_17_fallback_path(self, mock_redis, mock_vault, mock_alpaca, mock_snapshot):
        """Piece 17: Verify fallback to close when snapshot fails."""
        mock_vault.return_value = {"active_gear": 10, "gold": {"params": {}, "id": 1}}
        
        df_mock = pd.DataFrame({
            "ts": [pd.Timestamp.now()],
            "open": [100.0], "high": [105.0], "low": [95.0], "close": [102.0], "volume": [1000],
            "symbol": ["AAPL"]
        }).set_index("ts")
        mock_alpaca.return_value = df_mock
        
        # Simulate snapshot failure
        mock_snapshot.side_effect = Exception("API Timeout")
        
        captured_df = []
        def mock_process(data):
            captured_df.append(data)
            
        with patch.object(self.orchestrator, "_process_frame", side_effect=mock_process):
            self.thalamus.pulse(symbols=["AAPL"], pulse_type="SEED")
            
        df = captured_df[0]
        self.assertEqual(df["bid"].iloc[0], 102.0) # Fallback to close
        self.assertEqual(df["ask"].iloc[0], 102.0) # Fallback to close
        self.assertEqual(df["bid_size"].iloc[0], 0.0)
        self.assertEqual(df["ask_size"].iloc[0], 0.0)

    @patch("Thalamus.relay.service.Thalamus.get_snapshot")
    @patch("Hippocampus.Archivist.librarian.librarian.get_hormonal_vault")
    @patch("Hippocampus.Archivist.librarian.librarian.get_redis_connection")
    async def test_piece_18_websocket_on_bar_path(self, mock_redis, mock_vault, mock_snapshot):
        """Piece 18: Verify _on_bar path produces bid/ask."""
        mock_vault.return_value = {"active_gear": 10, "gold": {"params": {}, "id": 1}}
        
        # Mock Bar object
        bar_mock = MagicMock()
        bar_mock.symbol = "BTC/USD"
        bar_mock.open = 50000.0
        bar_mock.high = 50100.0
        bar_mock.low = 49900.0
        bar_mock.close = 50050.0
        bar_mock.volume = 1.5
        bar_mock.timestamp = pd.Timestamp.now(tz="UTC")
        
        # Mock Snapshot
        class MockQuote:
            bid_price = 50045.0
            ask_price = 50055.0
            bid_size = 0.5
            ask_size = 0.5

        class MockSnapshot:
            latest_quote = MockQuote()
            
        mock_snapshot.return_value = {"BTC/USD": MockSnapshot()}
        
        captured_drip = []
        def mock_drip(data):
            captured_drip.append(data)
            
        with patch.object(self.thalamus, "drip_pulse", side_effect=mock_drip):
            # Simulate Alpaca WebSocket callback
            await self.thalamus._on_bar(bar_mock)
            
        self.assertTrue(len(captured_drip) > 0)
        df = captured_drip[0]
        self.assertIn("bid", df.columns)
        self.assertIn("ask", df.columns)
        self.assertEqual(df["bid"].iloc[0], 50045.0)
        self.assertEqual(df["ask"].iloc[0], 50055.0)

    @patch("Hippocampus.Archivist.librarian.librarian.get_hormonal_vault")
    @patch("Hippocampus.Archivist.librarian.librarian.get_redis_connection")
    async def test_piece_19_warmup_context_fallback(self, mock_redis, mock_vault):
        """Piece 19: Verify warmup context runs without crashing (fallback to close)."""
        mock_vault.return_value = {"active_gear": 10, "gold": {"params": {}, "id": 1}}
        
        # Mock bars data enriched with bid/ask (simulating _normalize_bars inside _pulse_from_alpaca)
        # Use 10 bars (10 minutes) to trigger a MINT pulse (window rollover)
        ts_range = pd.date_range(end=pd.Timestamp.now().floor("5min"), periods=10, freq="1min")
        df_mock = pd.DataFrame({
            "open": [100.0] * 10, "high": [105.0] * 10, "low": [95.0] * 10, "close": [102.0] * 10, "volume": [1000.0] * 10,
            "symbol": ["AAPL"] * 10,
            "bid": [102.0] * 10, "ask": [102.0] * 10, "bid_size": [0.0] * 10, "ask_size": [0.0] * 10
        }, index=ts_range)
        
        with patch.object(self.thalamus, "_pulse_from_alpaca", return_value=df_mock):
            # Warmup (defaults to 60m internally)
            self.thalamus.warmup_context(symbols=["AAPL"], is_crypto=False)
            
        # Verify SmartGland context contains the enriched bars
        ctx = self.thalamus.gland.context_df
        self.assertFalse(ctx.empty)
        # Check if bid/ask columns were added
        self.assertIn("bid", ctx.columns)
        self.assertIn("ask", ctx.columns)
        self.assertEqual(ctx["bid"].iloc[0], 102.0)
        self.assertEqual(ctx["ask"].iloc[0], 102.0)

if __name__ == "__main__":
    unittest.main()
