import json
import time
import numpy as np
from pathlib import Path
from typing import Dict, Any, List, Optional
from dataclasses import dataclass

from Hippocampus.Archivist.librarian import librarian
from Hospital.Optimizer_loop.bounds import MINS, MAXS, normalize_weights, PARAM_KEYS

# Piece 149: Phase 1 execution/sizing parameter bounds
PHASE1_PARAM_BOUNDS = {
    "spread_tight_threshold_bps": (0.1, 50.0),
    "spread_normal_threshold_bps": (1.0, 100.0),
    "spread_wide_threshold_bps": (5.0, 500.0),
    "spread_score_scalar": (0.1, 10.0),
    "spread_atr_ratio": (0.01, 1.0),
    "council_w_spread": (0.0, 1.0),
    "fee_maker_bps": (0.0, 50.0),
    "fee_taker_bps": (0.0, 50.0),
    "fee_fallback_pct": (0.0, 0.01),
    "max_slippage_bps": (1.0, 500.0),
    "slippage_impact_scalar": (0.0, 1.0),
    "slippage_vol_scalar": (0.0, 1.0),
    "max_cost_cap_bps": (1.0, 200.0),
    "risk_per_trade_pct": (0.0001, 0.1),
    "max_notional": (100.0, 1000000.0),
    "max_qty": (0.0001, 10000.0),
    "min_qty": (0.0, 1.0),
    "max_z": (0.1, 10.0),
    "cost_penalty_divisor": (1.0, 1000.0),
    "max_cost_penalty": (0.0, 1.0),
    "equity": (1.0, 10000000.0),
    "brain_stem_val_n_sigma": (0.1, 5.0),
    "crawler_lookback_hours": (1, 168),
    "crawler_silver_top_n": (1, 50)
}

@dataclass
class Hormone:
    name: str # platinum, gold, silver, bronze
    params: Dict[str, Any]
    fitness: float
    source: str # e.g. "forge-123", "manual", "synapse-456"

class PituitaryGland:
    """
    Root Pituitary: The Master Hormonal Controller.
    Manages the hierarchy of trading genetics:
    1. Platinum: The bleeding-edge optimized set (Automated).
    2. Gold: The stable reference set (Manual).
    3. Silver: Historical high-performers (Synapse Memory).
    4. Bronze: The Fall-off list (Retired).

    V3.3 EVOLUTION: GP Mutation archived. Gold only changes through
    Crawler PROMOTE events or manual intervention.
    """
    def __init__(self):
        self.root = Path(__file__).resolve().parents[1]
        self.params_root = self.root / "params"
        self.platinum_path = self.params_root / "platinum_params.json"
        self.gold_path = self.params_root / "gold_params.json"
        self.bronze_path = self.params_root / "bronze_list.json"
        
        # Piece 115: Librarian handles Redis-based vault storage
        self.librarian = librarian

    def secrete_growth_hormone(self, pulse_type: str):
        """Piece 183: Stubbed. GP Mutation is archived in favor of Interleaved Furnace."""
        pass

    def validate_hormonal_integrity(self, params: Dict[str, Any], repair: bool = False) -> bool:
        """
        Piece 14 Safety Gate (Piece 15):
        Ensures all 23-D keys are present and values are within absolute MIN/MAX bounds.
        Also validates 24 Phase 1 execution/sizing parameters.
        V5: Standardized MNER [PITU-E-...] reporting.
        """
        is_valid = True
        
        # 1. Validate Canonical 23-D Optimizer Params
        for i, key in enumerate(PARAM_KEYS):
            if key not in params:
                # [PITU-E-P14-901] Missing Key
                print(f"   [PITU-E-P14-901] INTEGRITY_GATE_FAIL: Missing optimizer key '{key}'")
                return False
            
            val = float(params[key])
            low, high = MINS[i], MAXS[i]
            
            if val < low or val > high:
                is_valid = False
                if repair:
                    clamped = np.clip(val, low, high)
                    print(f"   [PITU-W-P14-902] INTEGRITY_REPAIR: {key} ({val:.4f}) clamped to [{low}, {high}]")
                    params[key] = clamped
                else:
                    # [PITU-E-P14-903] Bound Violation
                    print(f"   [PITU-E-P14-903] INTEGRITY_GATE_FAIL: {key} ({val:.4f}) outside [{low}, {high}]")

        # 2. Validate Phase 1 Execution/Sizing Params (Piece 149)
        for key, (low, high) in PHASE1_PARAM_BOUNDS.items():
            if key in params:
                val = float(params[key])
                if val < low or val > high:
                    is_valid = False
                    if repair:
                        clamped = np.clip(val, low, high)
                        print(f"   [PITU-W-P149-904] INTEGRITY_REPAIR: {key} ({val:.4f}) clamped to [{low}, {high}]")
                        params[key] = clamped
                    else:
                        # [PITU-E-P149-905] Bound Violation (Phase 1)
                        print(f"   [PITU-E-P149-905] INTEGRITY_GATE_FAIL: {key} ({val:.4f}) outside [{low}, {high}]")
        
        return is_valid or repair

    def secrete_platinum(self, regime_id: str, new_params: Dict[str, Any], fitness: float) -> bool:
        """
        Attempts to update the Platinum standard. 
        If successful, the old Platinum is retired to Bronze.
        """
        # Piece 14 Safety Gate: Platinum must also pass the gate
        if not self.validate_hormonal_integrity(new_params, repair=True):
            # [PITU-E-P189-906] Platinum Gate Failure
            print(f"[PITU-E-P189-906] PLATINUM_ABORTED: New params for {regime_id} failed integrity gate.")
            return False

        vault = self.librarian.get_hormonal_vault()
        current_plat = vault.get("platinum", {})
        current_fitness = current_plat.get("fitness_estimate", 0.0)
        
        if fitness > current_fitness:
            print(f"[PITUITARY] New Platinum Standard! ({fitness:.4f} > {current_fitness:.4f})")
            
            # Retire old Platinum to Bronze if it existed
            if current_plat:
                self._retire_to_bronze(current_plat, reason="dethroned_by_platinum")
            
            # Mint new Platinum
            param_id = f"forge_{regime_id}_{int(time.time())}"
            new_entry = {
                "id": param_id,
                "params": new_params,
                "fitness_estimate": fitness,
                "minted_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
                "origin": "VolumeFurnace"
            }
            vault["platinum"] = new_entry
            self.librarian.set_hormonal_vault(vault)
            
            # Piece 189: Record in Param DB
            self.librarian.record_param_set(param_id, "PLATINUM", new_params, regime_id, fitness, "VolumeFurnace")
            
            return True
            
        return False

    def _retire_to_bronze(self, entry: Dict[str, Any], reason: str):
        """Moves an entry to the bronze list in the vault."""
        vault = self.librarian.get_hormonal_vault()
        bronze_list = vault.get("bronze", [])
        if not isinstance(bronze_list, list): bronze_list = []
        
        entry["retired_at"] = time.strftime("%Y-%m-%dT%H:%M:%S")
        entry["retirement_reason"] = reason
        
        bronze_list.append(entry)
        if len(bronze_list) > 100:
            bronze_list = bronze_list[-100:]
            
        vault["bronze"] = bronze_list
        self.librarian.set_hormonal_vault(vault)

    def _params_to_vector(self, params: Dict[str, Any]) -> Optional[np.ndarray]:
        """Piece 208: Converts a flat param dict to a 46-D numpy vector."""
        try:
            vec = np.array([float(params[k]) for k in PARAM_KEYS])
            return vec
        except (KeyError, TypeError, ValueError) as e:
            print(f"[PITU-E-P208] PARAMS_TO_VECTOR_FAILED: {e}")
            return None

    def _vector_to_params(self, vec: np.ndarray) -> Dict[str, Any]:
        """Piece 208: Converts a 46-D numpy vector to a flat param dict."""
        params = {}
        for i, key in enumerate(PARAM_KEYS):
            val = float(vec[i])
            # Integer casting for gears and lookbacks
            if key in ["active_gear", "crawler_lookback_hours", "crawler_silver_top_n"]:
                val = int(round(val))
            params[key] = val
        return params
