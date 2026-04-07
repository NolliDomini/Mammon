import numpy as np

# Definitive 23-Dimensional Search Space for Mammon V3
# Order: 
# 0: active_gear
# 1: monte_noise_scalar
# 2-4: monte_weights (worst, neutral, best)
# 5-8: council_weights (atr, adx, vol, vwap)
# 9-10: gatekeeper_thresholds (min_monte, min_council)
# 11-14: callosum_weights (monte, right, adx, weak)
# 15-17: brain_stem_params (w_turtle, w_council, survival)
# 18-20: brain_stem_scalars (noise, sigma, bias)
# 21-22: exits (stop_loss, breakeven)

MINS = np.array([
    5,    # 0: Gear
    0.05, # 1: Monte Noise
    0.0, 0.0, 0.0, # 2-4: Monte Weights
    0.0, 0.0, 0.0, 0.0, # 5-8: Council Weights
    0.1, 0.1, # 9-10: Gatekeeper
    0.0, 0.0, 0.0, 0.0, # 11-14: Callosum
    0.0, 0.0, 0.1, # 15-17: BS Logic
    0.01, 0.05, 0.01, # 18-20: BS Scalars
    1.5, 1.0  # 21-22: Exits
])

MAXS = np.array([
    60,   # 0: Gear
    2.0,  # 1: Monte Noise
    1.0, 1.0, 1.0, # 2-4: Monte Weights
    1.0, 1.0, 1.0, 1.0, # 5-8: Council Weights
    0.9, 0.9, # 9-10: Gatekeeper
    1.0, 1.0, 1.0, 1.0, # 11-14: Callosum
    1.0, 1.0, 0.9, # 15-17: BS Logic
    0.5, 1.0, 0.5, # 18-20: BS Scalars
    12.0, 10.0 # 21-22: Exits
])

def normalize_weights(raw_row):
    """Robustly normalizes the four weight groups in a 23-D row."""
    s = raw_row.copy()
    
    # 1. Monte (2-4)
    m_sum = np.sum(s[2:5]) + 1e-9
    s[2:5] /= m_sum
    
    # 2. Council (5-8)
    c_sum = np.sum(s[5:9]) + 1e-9
    s[5:9] /= c_sum
    
    # 3. Callosum (11-14)
    cl_sum = np.sum(s[11:15]) + 1e-9
    s[11:15] /= cl_sum
    
    # 4. Brain Stem (15-16)
    bs_sum = np.sum(s[15:17]) + 1e-9
    s[15:17] /= bs_sum
    
    return s

def calculate_batch_fitness(scaled_batch, min_cumsum, dist_to_stop):
    """
    V3.3 OPTIMIZER KERNEL (Gated Logic).
    Calculates Risk Score (Small Monte) and applies the Risk Gate (>0.5).
    """
    # 1. Parameter Extraction
    gears = np.clip(scaled_batch[:, 0].astype(int) - 1, 0, 59)
    noise_scalars = scaled_batch[:, 1].reshape(1, -1) # Row vector for broadcasting
    
    # 2. Fetch min_cumsum for all candidates: Result is (P, B)
    # min_cumsum is (P, 60), gears is (B,)
    M = min_cumsum[:, gears] 
    
    # 3. Survival Matrix (B,)
    # Survival if (M * mult * noise_scalar) > dist_to_stop
    s_worst   = np.mean((M * 2.0 * noise_scalars) > dist_to_stop, axis=0)
    s_neutral = np.mean((M * 1.0 * noise_scalars) > dist_to_stop, axis=0)
    s_best    = np.mean((M * 0.5 * noise_scalars) > dist_to_stop, axis=0)
    
    # 4. Weighted Risk Score (B,)
    # Monte Weights are at scaled_batch[:, 2:5]
    risk_score = (scaled_batch[:, 2] * s_worst) + (scaled_batch[:, 3] * s_neutral) + (scaled_batch[:, 4] * s_best)
    
    # 5. Apply Risk Gate (> 0.5)
    # If the score is <= 0.5, the trade is BLOCKED by the gate. 
    # The optimizer should punish this because we want to find winning parameters.
    # However, if the trade was a LOSER, blocking it is GOOD.
    # But min_cumsum here represents random walks, not history. We assume these are candidates for trade entry.
    # So we want High Confidence (Score > 0.5) that yields High Survival.
    
    # Simple Logic: Maximize the Score, but penalize weak scores heavily to push them above 0.5
    # If score <= 0.5, we slash it.
    
    gated_fitness = np.where(risk_score > 0.5, risk_score, risk_score * 0.5)
    
    return gated_fitness
