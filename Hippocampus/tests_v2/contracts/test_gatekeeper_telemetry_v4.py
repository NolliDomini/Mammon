import unittest
from Medulla.gatekeeper.service import Gatekeeper
from Cerebellum.Soul.brain_frame.service import BrainFrame
from unittest.mock import patch

class TestGatekeeperTelemetryV4(unittest.TestCase):
    @patch("Medulla.gatekeeper.service.librarian.write")
    def test_piece_136_telemetry_fields(self, mock_write):
        """Piece 136: Verify Gatekeeper telemetry includes Phase 1 fields."""
        gk = Gatekeeper()
        frame = BrainFrame()
        
        # Setup inputs
        frame.environment.spread_regime = "WIDE"
        frame.execution.total_cost_bps = 45.0
        frame.command.cost_adjusted_conviction = 0.65
        
        # Calculate
        gk.decide("ACTION", frame)
        
        # Verify telemetry
        tel = gk.last_telemetry
        self.assertIn("spread_regime", tel["inputs"])
        self.assertIn("total_cost_bps", tel["inputs"])
        self.assertIn("cost_adjusted_conviction", tel["inputs"])
        
        self.assertEqual(tel["inputs"]["spread_regime"], "WIDE")
        self.assertEqual(tel["inputs"]["total_cost_bps"], 45.0)
        self.assertEqual(tel["inputs"]["cost_adjusted_conviction"], 0.65)

if __name__ == "__main__":
    unittest.main()
