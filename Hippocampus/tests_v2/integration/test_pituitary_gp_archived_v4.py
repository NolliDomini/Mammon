import unittest
from unittest.mock import MagicMock, patch
from Pituitary.gland.service import PituitaryGland

class TestPituitaryGPArchivedV4(unittest.TestCase):
    @patch("Pituitary.gland.service.librarian.get_hormonal_vault")
    @patch("Pituitary.gland.service.librarian.set_hormonal_vault")
    def test_piece_186_gp_secretion_disabled(self, mock_set, mock_get):
        """Piece 186: Verify GP mutation no longer triggers."""
        initial_vault = {
            "gold": {"id": "v1", "params": {"active_gear": 5}},
            "platinum": {}, "silver": []
        }
        mock_get.return_value = initial_vault
        
        pg = PituitaryGland()
        
        # Trigger 10 MINT pulses
        for _ in range(10):
            pg.secrete_growth_hormone("MINT")
            
        # Verify set_hormonal_vault was NEVER called (GP mutation would have called it)
        self.assertFalse(mock_set.called)
        
        # Verify gold remains unchanged
        self.assertEqual(initial_vault["gold"]["id"], "v1")
        print("[TEST] Pituitary GP Archive Verified (No Mutation).")

if __name__ == "__main__":
    unittest.main()
