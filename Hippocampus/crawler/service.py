import pandas as pd
import numpy as np
import time
from typing import Any, Dict, Optional
from Hippocampus.Archivist.librarian import librarian
from Pituitary.refinery.service import SynapseRefinery

import uuid

class ParamCrawler:
    """
    Hippocampus/Crawler: The Dual-Mode Genetic Engine.
    Piece 224: Dual-mode support (MINE / PROMOTE).
    """
    def __init__(self):
        self.librarian = librarian
        self.refinery = SynapseRefinery()
        self.last_mine_ts = 0
        
    def crawl(self, pulse_type: str, frame: Any):
        """Piece 224: Core entry point for the crawler logic."""
        if pulse_type != "MINT":
            return
            
        # Determine mode from vault
        vault = self.librarian.get_hormonal_vault()
        
        # 1. Mode MINE: Fills Silver
        self._run_mine_mode(vault, frame)
        
        # 2. Mode PROMOTE: Titanium -> Gold
        self._run_promote_mode(vault, frame)

    def _re_synthesize_tier_score(self, params: Dict[str, Any], tickets: pd.DataFrame) -> np.ndarray:
        """
        Piece 227: Vectorized re-synthesis of tier_score for a candidate param set.
        Blends historical Monte and Structure signals using the candidate's weights.
        """
        # 1. Extract raw signals and weights
        monte = tickets["monte_score"].to_numpy(dtype=np.float64)
        structure = tickets["tier1_signal"].to_numpy(dtype=np.float64)
        
        w_monte = float(params.get("callosum_w_monte", 0.70))
        w_right = float(params.get("callosum_w_right", 0.30))
        
        # 2. Vectorized blending: tier_score = (monte * w_monte) + (signal * w_right)
        # Piece 49: Standard blended synthesis logic
        re_synthesized_scores = (monte * w_monte) + (structure * w_right)
        
        # 3. Piece 14: Clamp to [0, 1]
        return np.clip(re_synthesized_scores, 0.0, 1.0)

    def _replay_params(self, params: Dict[str, Any], tickets: pd.DataFrame) -> float:
        """
        Piece 226: Production-grade Replay Kernel.
        Grounds re-synthesized scores against realized market behavior (PnL).
        """
        if tickets.empty:
            return 0.0
            
        try:
            # 1. Re-synthesize scores for these params
            scores = self._re_synthesize_tier_score(params, tickets)
            
            # 2. Extract realized PnL grounding
            # If PnL exists, it acts as a 'Truth' multiplier. 
            # High score + Positive PnL = High Fitness. 
            # High score + Negative PnL = Penalty.
            pnl = tickets["realized_pnl"].to_numpy(dtype=np.float64) if "realized_pnl" in tickets.columns else np.ones_like(scores)
            
            # 3. Vectorized Fitness: Score weighted by PnL performance
            # (Basic kernel: mean of score * (1 + pnl_mult))
            fitness_kernel = scores * (1.0 + np.tanh(pnl)) 
            
            return float(np.mean(fitness_kernel))
        except Exception as e:
            # [CRAWL-E-MINE-1002] REPLAY_KERNEL_FAILED
            print(f"[CRAWL-E-MINE-1002] REPLAY_KERNEL_FAILED: {e}")
            return 0.0

    def _run_mine_mode(self, vault: Dict[str, Any], frame: Any):
        """
        Piece 229-234: Mode MINE.
        Harvests high-performing historical param sets from Param DB and synapse.
        """
        gold = vault.get("gold", {})
        standards = gold.get("params", {})
        
        # 1. Cadence check
        interval = int(standards.get("crawler_mine_interval", 12))
        now = time.time()
        if (now - self.last_mine_ts) < (interval * 300): # MINTs to seconds (approx)
            return
            
        print(f"[CRAWLER] event=mine_start run_id={frame.market.machine_code[:8] if hasattr(frame.market, 'machine_code') else 'UNK'}")
        self.last_mine_ts = now
        
        # 2. Lookback & Harvest (Piece 228)
        lookback = int(standards.get("crawler_lookback_hours", 24))
        tickets = self.refinery.harvest_training_data(hours=lookback)
        if tickets.empty:
            # Piece 243: MNER NO_TICKETS_FOR_REPLAY
            print(f"[CRAWL-E-MINE-1001] NO_TICKETS_FOR_REPLAY: hours={lookback}")
            return
            
        # 3. Query historical param sets (Piece 229)
        # We'll pull from the Param DB history via Librarian
        history = self.librarian.get_param_history(limit=50) # Last 50 candidates
        if not history:
            return
            
        # 4. Replay and Score (Piece 230)
        scored_candidates = []
        for entry in history:
            params = entry.get("params")
            if not params: continue
            
            fitness = self._replay_params(params, tickets)
            scored_candidates.append({
                "params": params,
                "fitness": fitness,
                "regime_id": entry.get("regime_id", "UNK"),
                "source": entry.get("source", "historical_replay")
            })
            
        # 5. Top N performers (Piece 231)
        top_n = int(standards.get("crawler_silver_top_n", 5))
        scored_candidates.sort(key=lambda x: x["fitness"], reverse=True)
        winners = scored_candidates[:top_n]
        
        # 6. Write to Silver + Param DB (Piece 232)
        # record_silver_candidate handles the Silver cap (Piece 197)
        for i, winner in enumerate(winners):
            win_regime = str(winner.get("regime_id", "UNK"))
            # Unique ID per winner in batch
            param_id = f"silver_{win_regime}_{uuid.uuid4().hex[:8]}"
            self.librarian.record_silver_candidate(
                winner["params"], 
                winner["fitness"], 
                win_regime, 
                winner["source"]
            )
            
        print(f"[CRAWLER] event=mine_complete winners={len(winners)}")

    def _run_promote_mode(self, vault: Dict[str, Any], frame: Any):
        """
        Piece 235-242: Mode PROMOTE.
        Evaluates Titanium candidate over soak_window and promotes if successful.
        """
        titanium = vault.get("titanium")
        if not titanium or not titanium.get("soak_active", False):
            return
            
        gold = vault.get("gold", {})
        standards = gold.get("params", {})
        
        # 1. Score Titanium against current pulse (Piece 236)
        # Simplified: Use current pulse tier_score as a proxy for soak performance
        current_score = float(frame.risk.monte_score)
        
        soak_scores = titanium.get("soak_scores", [])
        soak_scores.append(current_score)
        
        # 2. Check soak window (Piece 237)
        soak_window = int(standards.get("soak_window", 12))
        if len(soak_scores) < soak_window:
            # Continue soaking
            titanium["soak_scores"] = soak_scores
            vault["titanium"] = titanium
            self.librarian.set_hormonal_vault(vault)
            return
            
        # 3. Decision Time (Piece 238)
        try:
            avg_titanium_fitness = float(np.mean(soak_scores))
        except Exception as e:
            # Piece 244: MNER SOAK_SCORE_INVALID
            print(f"[CRAWL-E-PROM-1003] SOAK_SCORE_INVALID: {e}")
            return

        gold_fitness = float(gold.get("fitness_snapshot", gold.get("fitness_estimate", gold.get("fitness", 0.5))))
        delta = float(standards.get("promotion_delta", 0.05))
        
        try:
            if avg_titanium_fitness > (gold_fitness + delta):
                # PROMOTE (Piece 239)
                print(f"[CRAWLER] event=promote challenger={titanium['id']} incumbent={gold['id']}")
                
                # Piece 224: Delegate coronation to the Pituitary via the Librarian's 
                # standardized interface. The Librarian already handles vault persistence 
                # and Gold installation.
                try:
                    self.librarian.install_gold_params(
                        params=titanium["params"],
                        fitness=avg_titanium_fitness,
                        origin="DiamondML",
                        regime_id=frame.risk.regime_id
                    )
                except Exception as install_err:
                    # Keep promotion path alive even when Param DB write path is unavailable.
                    print(f"[CRAWLER_WARN] install_gold_params failed, using vault fallback: {install_err}")
                    vault["gold"] = {
                        "id": str(titanium.get("id", f"diamond_promote_{int(time.time())}")),
                        "params": titanium["params"],
                        "fitness_snapshot": avg_titanium_fitness,
                        "coronated_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
                        "origin": "DiamondML",
                    }
                
                vault = self.librarian.get_hormonal_vault() # Re-load to get updated Gold
                vault["titanium"] = None # Clear soak
            else:
                # REJECT (Piece 241)
                print(f"[CRAWLER] event=reject_titanium id={titanium['id']} fitness={avg_titanium_fitness:.4f}")
                vault["titanium"] = None # Discard bad candidate
                
            self.librarian.set_hormonal_vault(vault)
        except Exception as e:
            # Piece 245: MNER PROMOTION_ABORTED
            print(f"[CRAWL-E-PROM-1004] PROMOTION_ABORTED: {e}")
