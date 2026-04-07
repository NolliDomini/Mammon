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

class PituitaryDaemon:
    """
    Pituitary: The Hormonal Command Center.
    Handles Diamond Deep Search and Silver-to-Gold Coronation.
    """
    def __init__(self):
        self.vault_path = project_root / "Hippocampus" / "hormonal_vault.json"
        self.diamond = DiamondGland()
        self.promotion_threshold = 0.05 # Silver must beat Gold by 5%

    def run_metabolism_cycle(self):
        print("\n" + "="*60)
        print(f"{'PITUITARY METABOLISM CYCLE STARTING':^60}")
        print("="*60)
        
        # 1. Diamond Deep Search (Update Safety Rails)
        self.diamond.perform_deep_search()
        
        # 2. Evaluate Coronation
        with open(self.vault_path, "r") as f:
            vault = json.load(f)
            
        silver = vault.get("silver")
        gold = vault.get("gold")
        
        if not silver:
            print("[PITUITARY] No Silver challenger found. Coronation skipped.")
        else:
            self._evaluate_coronation(vault, silver, gold)
            
        print("="*60)
        print(f"{'METABOLISM CYCLE COMPLETE':^60}")
        print("="*60 + "\n")

    def _evaluate_coronation(self, vault: Dict[str, Any], silver: Dict[str, Any], gold: Dict[str, Any]):
        print(f"[PITUITARY] Evaluating Coronation: Challenger {silver['id']} vs Incumbent {gold['id']}")
        
        # 1. The Clench (Audit against Rails)
        rails = vault["diamond_rails"]["bounds"]
        is_safe = True
        for param, bounds in rails.items():
            val = silver["params"].get(param)
            if val is not None and param in rails:
                # Basic safety check
                if val < bounds["min"] or val > bounds["max"]:
                    print(f"   [AUDIT FAIL] {param}: {val:.4f} is outside rails [{bounds['min']:.4f}, {bounds['max']:.4f}]")
                    is_safe = False
                    break
        
        if not is_safe:
            print("[PITUITARY] Challenger REJECTED: Safety rail violation.")
            vault["silver"] = None # Discard bad challenger
            self._save_vault(vault)
            return

        # 2. The Contest (Fitness Comparison)
        s_fitness = silver.get("fitness_estimate", 0)
        g_fitness = gold.get("fitness_snapshot", 0)
        
        if s_fitness > (g_fitness * (1 + self.promotion_threshold)):
            print(f"[PITUITARY] CHALLENGER WINS! {s_fitness:.4f} > {g_fitness:.4f}")
            self._coronate(vault, silver, gold)
        else:
            print(f"[PITUITARY] Incumbent Remains. Challenger fitness {s_fitness:.4f} too low to promote.")
            vault["silver"] = None # Clear silver for next furnace cycle
            self._save_vault(vault)

    def _coronate(self, vault: Dict[str, Any], silver: Dict[str, Any], gold: Dict[str, Any]):
        print(f"[PITUITARY] CORONATING NEW GOLD: {silver['id']}")
        
        # 1. Demote Gold to Bronze Genealogy
        gold["demoted_at"] = time.strftime("%Y-%m-%dT%H:%M:%S")
        vault["bronze_history"].insert(0, gold)
        
        # 2. Truncate Genealogy (Rolling 10)
        vault["bronze_history"] = vault["bronze_history"][:10]
        
        # 3. Install New Gold
        new_gold = {
            "id": silver["id"],
            "params": silver["params"],
            "fitness_snapshot": silver["fitness_estimate"],
            "coronated_at": time.strftime("%Y-%m-%dT%H:%M:%S")
        }
        vault["gold"] = new_gold
        vault["silver"] = None # Clear silver
        
        self._save_vault(vault)
        print(f"[PITUITARY] Genealogy Updated. History Length: {len(vault['bronze_history'])}")

    def _save_vault(self, vault: Dict[str, Any]):
        with open(self.vault_path, "w") as f:
            json.dump(vault, f, indent=2)

if __name__ == "__main__":
    daemon = PituitaryDaemon()
    daemon.run_metabolism_cycle()
