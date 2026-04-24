import numpy as np

# Definitive 46-Dimensional Search Space for Mammon V4
PARAM_KEYS = [
    "active_gear", "monte_noise_scalar",
    "monte_w_worst", "monte_w_neutral", "monte_w_best",
    "council_w_atr", "council_w_adx", "council_w_vol", "council_w_vwap", "council_w_spread",
    "gatekeeper_min_monte", "gatekeeper_min_council",
    "callosum_w_monte", "callosum_w_right", "callosum_w_adx", "callosum_w_weak",
    "brain_stem_w_turtle", "brain_stem_w_council", "brain_stem_survival",
    "brain_stem_noise", "brain_stem_sigma", "brain_stem_bias",
    "stop_loss_mult", "breakeven_mult",
    "spread_tight_threshold_bps", "spread_normal_threshold_bps", "spread_wide_threshold_bps",
    "spread_score_scalar", "spread_atr_ratio",
    "fee_maker_bps", "fee_taker_bps", "fee_fallback_pct",
    "max_slippage_bps", "slippage_impact_scalar", "slippage_vol_scalar", "max_cost_cap_bps",
    "risk_per_trade_pct", "max_notional", "max_qty", "min_qty", "max_z",
    "cost_penalty_divisor", "max_cost_penalty", "equity", "brain_stem_val_n_sigma",
    "crawler_lookback_hours", "crawler_silver_top_n"
]

MINS = np.array([
    5,    # 0: Gear
    0.05, # 1: Monte Noise
    0.0, 0.0, 0.0, # 2-4: Monte Weights
    0.0, 0.0, 0.0, 0.0, 0.0, # 5-9: Council Weights (incl spread)
    0.1, 0.1, # 10-11: Gatekeeper
    0.0, 0.0, 0.0, 0.0, # 12-15: Callosum
    0.0, 0.0, 0.1, # 16-18: BS Logic
    0.01, 0.05, 0.01, # 19-21: BS Scalars
    1.5, 1.0,  # 22-23: Exits
    0.1, 1.0, 5.0, 0.1, 0.01, # 24-28: Spread (tight, normal, wide, scalar, ratio)
    0.0, 0.0, 0.0, # 29-31: Fees (maker, taker, fallback)
    1.0, 0.0, 0.0, 1.0, # 32-35: Slippage (max, impact, vol, cap)
    0.0001, 100.0, 0.0001, 0.0, 0.1, 1.0, 0.0, 1.0, 0.1, # 36-44: Sizing (risk, notional, qty, min, z, div, penalty, equity, n_sigma)
    1, # 45: Lookback
    1  # 46: Top N
])

MAXS = np.array([
    60,   # 0: Gear
    2.0,  # 1: Monte Noise
    1.0, 1.0, 1.0, # 2-4: Monte Weights
    1.0, 1.0, 1.0, 1.0, 1.0, # 5-9: Council Weights (incl spread)
    0.9, 0.9, # 10-11: Gatekeeper
    1.0, 1.0, 1.0, 1.0, # 12-15: Callosum
    1.0, 1.0, 0.9, # 16-18: BS Logic
    0.5, 1.0, 0.5, # 19-21: BS Scalars
    12.0, 10.0, # 22-23: Exits
    50.0, 100.0, 500.0, 10.0, 1.0, # 24-28: Spread
    50.0, 50.0, 0.01, # 29-31: Fees
    500.0, 1.0, 1.0, 200.0, # 32-35: Slippage
    0.1, 1000000.0, 10000.0, 1.0, 10.0, 1000.0, 1.0, 10000000.0, 5.0, # 36-44: Sizing
    168, # 45: Lookback
    50   # 46: Top N
])

def normalize_weights(raw_row):
    """
    Piece 204: Robustly normalizes weight groups in a 46-D row.
    Enforces strict sum == 1.0 for each group.
    """
    s = raw_row.copy().astype(np.float64)
    
    # 1. Monte (2-4)
    m_slice = s[2:5]
    m_sum = np.sum(m_slice)
    if m_sum > 0:
        s[2:5] /= m_sum
    else:
        s[2:5] = np.array([0.33, 0.33, 0.34]) # Safe fallback
    
    # 2. Council (5-9) - Includes Spread (Piece 204)
    c_slice = s[5:10]
    c_sum = np.sum(c_slice)
    if c_sum > 0:
        s[5:10] /= c_sum
    else:
        s[5:10] = np.array([0.2, 0.2, 0.2, 0.2, 0.2])
    
    # 3. Callosum (12-15)
    cl_slice = s[12:16]
    cl_sum = np.sum(cl_slice)
    if cl_sum > 0:
        s[12:16] /= cl_sum
    else:
        s[12:16] = np.array([0.25, 0.25, 0.25, 0.25])
    
    # 4. Brain Stem Weights (16-17)
    bs_slice = s[16:18]
    bs_sum = np.sum(bs_slice)
    if bs_sum > 0:
        s[16:18] /= bs_sum
    else:
        s[16:18] = np.array([0.5, 0.5])
    
    # Verification Guard
    for start, end in [(2,5), (5,10), (12,16), (16,18)]:
        group_sum = np.sum(s[start:end])
        if not np.isclose(group_sum, 1.0, atol=1e-7):
            s[start:end] /= (group_sum + 1e-9)
            
    return s

# Piece 205: Domain Slices for Split Optimization
DOMAIN_SLICES = {
    "RISK": {
        "indices": [1, 2, 3, 4, 18, 19, 20, 21], # monte_noise, monte_weights, BS survival/noise/sigma/bias
        "description": "Risk trajectory and survival lane blending."
    },
    "STRATEGY": {
        "indices": [0, 10, 11, 22, 23], # active_gear, gatekeeper_min_monte/min_council, stop_loss/breakeven
        "description": "Core breakout gears and entry/exit thresholds."
    },
    "COUNCIL": {
        "indices": [5, 6, 7, 8, 9, 24, 25, 26, 27, 28], # council_weights (5), spread thresholds/scalar/atr_ratio
        "description": "Environmental indicators and liquidity friction."
    },
    "SYNTHESIS": {
        "indices": [12, 13, 14, 15, 16, 17], # callosum_weights, BS w_turtle/w_council
        "description": "Lobe signal blending and prior biasing."
    },
    "EXECUTION": {
        "indices": [29, 30, 31, 32, 33, 34, 35, 36, 37, 38, 39, 40, 41, 42, 43, 44, 45, 46], # fees, slippage, sizing, valuation sigma, crawler
        "description": "Pre-trade friction and position sizing logic."
    }
}

def get_domain_vector(full_vector, domain: str):
    """Extracts a sub-vector for a specific domain."""
    indices = DOMAIN_SLICES.get(domain.upper(), {}).get("indices", [])
    return full_vector[indices]

def merge_domain_vector(gold_vector, domain_vector, domain: str):
    """Merges a domain sub-vector back into a full vector (usually Gold)."""
    indices = DOMAIN_SLICES.get(domain.upper(), {}).get("indices", [])
    merged = gold_vector.copy()
    merged[indices] = domain_vector
    return merged

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
