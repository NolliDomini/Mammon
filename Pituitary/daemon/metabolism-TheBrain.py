import sys
import json
import time
from pathlib import Path
from typing import Dict, Any

# Setup project root
project_root = Path(__file__).resolve().parents[2]
if str(project_root) not in sys.path:
    sys.path.insert(0, str(project_root))

from Pituitary.search.diamond import DiamondGland
from Hippocampus.Archivist.librarian import librarian

class PituitaryDaemon:
    """
    Pituitary: The Hormonal Command Center.
    Handles Diamond Deep Search and Silver-to-Gold Coronation.
    V5: Using Librarian for all vault I/O (Multi-Transport).
    """
    def __init__(self):
        self.librarian = librarian
        self.diamond = DiamondGland()
        self.promotion_threshold = 0.05 # Silver must beat Gold by 5%

    def run_metabolism_cycle(self):
        print("\n" + "="*60)
        print(f"{'PITUITARY METABOLISM CYCLE STARTING':^60}")
        print("="*60)
        
        # 1. Diamond Deep Search (Update Safety Rails)
        self.diamond.perform_deep_search()
        
        # 2. Evaluate Coronation
        # Piece 115: Atomic Vault Read via Librarian (Redis/JSON)
        vault = self.librarian.get_hormonal_vault()
            
        silver = vault.get("silver")
        gold = vault.get("gold")
        
        # NOTE: Silver in the vault can be a list or a single dict.
        # Original daemon logic expected a single dict. Modern V4 vault uses a list.
        if isinstance(silver, list) and len(silver) > 0:
            # Pick the top fitness Silver from the list for evaluation
            sorted_silver = sorted(silver, key=lambda x: x.get("fitness", 0), reverse=True)
            challenger = sorted_silver[0]
            self._evaluate_coronation(vault, challenger, gold)
        elif isinstance(silver, dict):
            self._evaluate_coronation(vault, silver, gold)
        else:
            print("[PITUITARY] No Silver challenger found. Coronation skipped.")
            
        print("="*60)
        print(f"{'METABOLISM CYCLE COMPLETE':^60}")
        print("="*60 + "\n")

    def _evaluate_coronation(self, vault: Dict[str, Any], silver: Dict[str, Any], gold: Dict[str, Any]):
        print(f"[PITUITARY] Evaluating Coronation: Challenger {silver.get('id', 'UNK')} vs Incumbent {gold.get('id', 'UNK')}")
        
        # 1. The Clench (Audit against Rails)
        # Piece 149: Standardized Hormonal Validation
        from Pituitary.gland.service import PituitaryGland
        pg = PituitaryGland()
        if not pg.validate_hormonal_integrity(silver["params"], repair=True):
            print("[PITUITARY] Challenger REJECTED: Integrity Gate failure.")
            self._discard_silver(silver["id"])
            return

        rails = vault.get("diamond_rails", {}).get("bounds", {})
        is_safe = True
        for param, bounds in rails.items():
            val = silver["params"].get(param)
            if val is not None and param in rails:
                if val < bounds["min"] or val > bounds["max"]:
                    print(f"   [AUDIT FAIL] {param}: {val:.4f} is outside rails [{bounds['min']:.4f}, {bounds['max']:.4f}]")
                    is_safe = False
                    break
        
        if not is_safe:
            print("[PITUITARY] Challenger REJECTED: Safety rail violation.")
            self._discard_silver(silver["id"])
            return

        # 2. The Contest (Fitness Comparison)
        s_fitness = float(silver.get("fitness_estimate", silver.get("fitness", 0)))
        g_fitness = float(gold.get("fitness_snapshot", gold.get("fitness", 0.5)))
        
        # Piece 238: Same delta logic as Crawler
        delta = float(gold.get("params", {}).get("promotion_delta", 0.05))
        if s_fitness > (g_fitness + delta):
            print(f"[PITUITARY] CHALLENGER WINS! {s_fitness:.4f} > {g_fitness:.4f}")
            self._coronate(vault, silver, gold)
        else:
            print(f"[PITUITARY] Incumbent Remains. Challenger fitness {s_fitness:.4f} too low to promote.")
            self._discard_silver(silver["id"])

    def _coronate(self, vault: Dict[str, Any], silver: Dict[str, Any], gold: Dict[str, Any]):
        print(f"[PITUITARY] CORONATING NEW GOLD: {silver['id']}")
        
        # Piece 188: Standardized Coronation Authority
        self.librarian.install_gold_params(
            params=silver["params"],
            fitness=float(silver.get("fitness_estimate", silver.get("fitness", 0))),
            origin="DiamondML",
            regime_id=silver.get("regime_id", "GLOBAL")
        )
        self._discard_silver(silver["id"])
        print(f"[PITUITARY] Piece 188: Coronation Successful.")

    def _discard_silver(self, silver_id: str):
        """Standardized silver cleanup."""
        vault = self.librarian.get_hormonal_vault()
        if isinstance(vault.get("silver"), dict):
            vault["silver"] = None
        elif isinstance(vault.get("silver"), list):
            vault["silver"] = [s for s in vault["silver"] if s.get("id") != silver_id]
        self.librarian.set_hormonal_vault(vault)

if __name__ == "__main__":
    daemon = PituitaryDaemon()
    daemon.run_metabolism_cycle()
