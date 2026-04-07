import os
import sys
import numpy as np
import json
from pathlib import Path

# Ensure Mammon root is on path
MAMMON_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(MAMMON_ROOT))

from Hospital.Optimizer_loop.optimizer_v2 import OptimizerV2Engine, V2Budget
from Hippocampus.Archivist.librarian import MultiTransportLibrarian as OptimizerLibrarian

def run_isolated_test():
    print("=== MAMMON OPTIMIZER V2: ISOLATED TEST ===")
    
    # 1. Setup Temporary DB
    test_db = MAMMON_ROOT / "isolated_test_optimizer.db"
    if test_db.exists():
        test_db.unlink()
        
    librarian = OptimizerLibrarian(db_path=test_db)
    librarian.setup_schema()
    
    # 2. Instantiate Engine
    budget = V2Budget(
        edge_lhs_n=64,
        island_n=12,
        top_k=6,
        refine_lhs_n=32,
        bayes_n=15,
        min_support=25
    )
    
    engine = OptimizerV2Engine(
        run_id="test-run-isolated",
        librarian=librarian,
        seed=42,
        budget=budget
    )
    
    # 3. Generate Mock Mutations (Regime Truth)
    # 100 paths, 60 steps each = 6000 mutations
    # Let's create a slightly bullish regime with 0.02% drift per step and 0.1% volatility
    n_steps = 60
    n_paths = 100
    drift = 0.0002
    volatility = 0.001
    
    rng = np.random.default_rng(42)
    mutations = rng.normal(drift, volatility, n_steps * n_paths).tolist()
    
    # 4. Input Parameters
    regime_id = "D2_A1_V1_T1"
    price = 100.0
    atr = 0.5
    stop_level = 98.5 # 1.5% stop
    
    print(f"Inputs: Price={price}, ATR={atr}, Stop={stop_level}, Regime={regime_id}")
    print(f"Mutations: {len(mutations)} values ({n_paths} paths @ {n_steps} steps)")
    
    # 5. Run Pipeline
    print("\nExecuting Pipeline...")
    summary = engine.run_pipeline(
        regime_id=regime_id,
        price=price,
        atr=atr,
        stop_level=stop_level,
        allow_bayesian=True,
        mutations=mutations
    )
    
    # 6. Full Printout
    print("\n=== PIPELINE SUMMARY ===")
    print(json.dumps(summary, indent=4))
    
    # 7. Query Detailed Logs from DB
    print("\n=== STAGE LOGS ===")
    import sqlite3
    with sqlite3.connect(test_db) as conn:
        cursor = conn.execute("SELECT stage_name, status, metrics_json, reason_code FROM opt_stage_runs ORDER BY id")
        for row in cursor.fetchall():
            print(f"Stage: {row[0]:<30} | Status: {row[1]:<10} | Reason: {row[3] or 'N/A'}")
            if row[2]:
                metrics = json.loads(row[2])
                print(f"   Metrics: {metrics}")

    print("\n=== WINNER COMPONENTS ===")
    with sqlite3.connect(test_db) as conn:
        cursor = conn.execute("""
            SELECT expectancy, survival, stability, drawdown, final_score, robust_score 
            FROM opt_scores_components 
            ORDER BY robust_score DESC LIMIT 1
        """)
        row = cursor.fetchone()
        if row:
            print(f"Expectancy: {row[0]:.4f}")
            print(f"Survival:   {row[1]:.4f}")
            print(f"Stability:  {row[2]:.4f}")
            print(f"Drawdown:   {row[3]:.4f}")
            print(f"Final:      {row[4]:.4f}")
            print(f"Robust:     {row[5]:.4f}")

    print("\n=== PROMOTION DECISION ===")
    with sqlite3.connect(test_db) as conn:
        cursor = conn.execute("SELECT decision, reason_code, score FROM opt_promotion_decisions LIMIT 1")
        row = cursor.fetchone()
        if row:
            print(f"Decision: {row[0]}")
            print(f"Reason:   {row[1]}")
            print(f"Score:    {row[2]:.4f}")

    # Cleanup
    if test_db.exists():
        test_db.unlink()

if __name__ == "__main__":
    run_isolated_test()
