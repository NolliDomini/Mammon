import unittest
import numpy as np
from Hospital.Optimizer_loop.bounds.service import DOMAIN_SLICES

class TestDomainSlicesV4(unittest.TestCase):
    def test_piece_206_slices_integrity(self):
        """Piece 206: Domain slices cover 46 indices with no overlap or gaps."""
        all_indices = []
        for domain, config in DOMAIN_SLICES.items():
            all_indices.extend(config["indices"])
            
        # 1. Check for duplicates (overlap)
        unique_indices = set(all_indices)
        self.assertEqual(len(all_indices), len(unique_indices), 
                         f"Overlap detected in domain slices! Duplicates: {[x for x in unique_indices if all_indices.count(x) > 1]}")
        
        # 2. Check for completeness (no gaps up to 46)
        expected_indices = set(range(47)) # 0 to 46 = 47 keys
        missing = expected_indices - unique_indices
        self.assertEqual(len(missing), 0, f"Gaps detected in domain slices! Missing: {missing}")
        
        print(f"[TEST] Piece 206: Domain Slices Verified. {len(unique_indices)} unique indices covered.")

if __name__ == "__main__":
    unittest.main()
