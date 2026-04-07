import unittest
import pandas as pd
from unittest.mock import MagicMock, patch
from Cerebellum.Soul.brain_frame.service import BrainFrame

class MockSubscriber:
    def __init__(self):
        self.received = False
        
    def on_data_received(self, pulse_type, frame):
        self.received = True
        # Simulate an old subscriber that only uses 'market' and 'structure'
        _ = frame.market.symbol
        _ = frame.structure.price

class TestBrainFrameV4Compatibility(unittest.TestCase):
    def test_piece_36_subscriber_tolerance(self):
        """ Piece 36: Subscribers must tolerate new slots without error. """
        frame = BrainFrame()
        sub = MockSubscriber()
        
        # This should NOT raise an error even though frame now has .valuation and .execution
        try:
            sub.on_data_received("ACTION", frame)
        except AttributeError as e:
            self.fail(f"Subscriber failed to handle expanded BrainFrame: {e}")
            
        self.assertTrue(sub.received)

    def test_piece_37_valuation_slot_defaults(self):
        """ Piece 37: Verify ValuationSlot safe defaults. """
        frame = BrainFrame()
        v = frame.valuation
        self.assertEqual(v.mean, 0.0)
        self.assertEqual(v.std_dev, 0.0)
        self.assertEqual(v.upper_band, 0.0)
        self.assertEqual(v.lower_band, 0.0)
        self.assertEqual(v.z_distance, 0.0)
        self.assertEqual(v.valuation_source, "NONE")

    def test_piece_38_execution_slot_defaults(self):
        """ Piece 38: Verify ExecutionSlot safe defaults. """
        frame = BrainFrame()
        e = frame.execution
        self.assertEqual(e.expected_slippage_bps, 0.0)
        self.assertEqual(e.expected_fee_bps, 0.0)
        self.assertEqual(e.total_cost_bps, 0.0)
        self.assertEqual(e.cost_inputs, {})

    def test_piece_39_reset_pulse_clears_all(self):
        """ Piece 39: Verify reset_pulse clears all Phase 1 fields. """
        frame = BrainFrame()
        
        # 1. Dirty the slots
        frame.environment.bid_ask_bps = 5.0
        frame.valuation.mean = 100.0
        frame.execution.total_cost_bps = 10.0
        frame.command.qty = 1.0
        frame.command.ready_to_fire = True
        
        # 2. Reset
        frame.reset_pulse("MINT")
        
        # 3. Verify
        self.assertEqual(frame.environment.bid_ask_bps, 0.0)
        self.assertEqual(frame.valuation.mean, 0.0)
        self.assertEqual(frame.execution.total_cost_bps, 0.0)
        self.assertEqual(frame.command.qty, 0.0)
        self.assertFalse(frame.command.ready_to_fire)
        self.assertEqual(frame.market.pulse_type, "MINT")

    def test_piece_40_to_synapse_dict_flattening(self):
        """ Piece 40: Verify to_synapse_dict flattens new slots correctly. """
        frame = BrainFrame()
        frame.environment.bid_ask_bps = 5.0
        frame.valuation.mean = 100.0
        frame.execution.total_cost_bps = 10.0
        frame.command.qty = 1.0
        
        synapse = frame.to_synapse_dict()
        
        # Verify flattening
        self.assertEqual(synapse["bid_ask_bps"], 5.0)
        self.assertEqual(synapse["val_mean"], 100.0)
        self.assertEqual(synapse["exec_total_cost_bps"], 10.0)
        self.assertEqual(synapse["qty"], 1.0)
        self.assertIn("machine_code", synapse)

    @patch("Cerebellum.Soul.brain_frame.service.librarian.get_redis_connection")
    def test_piece_41_redis_persistence(self, mock_redis_getter):
        """ Piece 41: Verify Redis check-in/out preserves new fields. """
        mock_redis = MagicMock()
        mock_redis_getter.return_value = mock_redis
        
        # 1. Setup frame with data
        frame = BrainFrame()
        frame.market.symbol = "ETH/USD"
        frame.market.execution_mode = "PAPER"
        frame.valuation.mean = 2500.0
        frame.command.qty = 0.5
        
        # 2. Check-in (writes to mock_redis)
        stored_data = {}
        def mock_set(key, val): stored_data[key] = val
        mock_redis.set.side_effect = mock_set
        
        frame.check_in()
        
        # 3. Check-out (reads from stored_data)
        mock_redis.get.side_effect = lambda k: stored_data.get(k)
        
        rehydrated = BrainFrame.check_out("ETH/USD", "PAPER")
        
        # 4. Verify
        self.assertIsNotNone(rehydrated)
        self.assertEqual(rehydrated.valuation.mean, 2500.0)
        self.assertEqual(rehydrated.command.qty, 0.5)
        self.assertEqual(rehydrated.market.symbol, "ETH/USD")

    def test_piece_42_optical_tract_spray_extended_df(self):
        """ Piece 42: Verify Optical Tract spray with extended columns. """
        from Corpus.Optical_Tract.spray import OpticalTract
        tract = OpticalTract()
        
        # Extended DF with new columns from Thalamus Phase 1
        df = pd.DataFrame({
            "open": [100.0], "close": [101.0], "symbol": ["AAPL"], "pulse_type": ["ACTION"],
            "bid": [100.5], "ask": [101.5], "bid_size": [10], "ask_size": [10]
        })
        
        # This should spray without raising Schema errors or similar
        res = tract.spray(df)
        self.assertEqual(res["pulse_type"], "ACTION")
        self.assertEqual(res["failed_count"], 0)

if __name__ == "__main__":
    unittest.main()
