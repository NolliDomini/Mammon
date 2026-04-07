import numpy as np
from numba import njit

@njit(cache=True)
def calculate_atr_njit(high_arr, low_arr, close_arr, window):
    """
    Piece 10: Standardized Vectorized ATR (Council Authority).
    Uses Numba for C-level speed.
    """
    n = len(high_arr)
    if n < window + 1:
        return np.zeros(n)
    
    tr = np.zeros(n)
    atr = np.zeros(n)
    
    # Calculate True Range
    for i in range(1, n):
        h_l = high_arr[i] - low_arr[i]
        h_pc = np.abs(high_arr[i] - close_arr[i-1])
        l_pc = np.abs(low_arr[i] - close_arr[i-1])
        tr[i] = max(h_l, max(h_pc, l_pc))
    
    # Initial ATR (SMA of TR)
    atr[window] = np.mean(tr[1:window+1])
    
    # Wilder's Smoothing
    alpha = 1.0 / window
    for i in range(window + 1, n):
        atr[i] = (tr[i] * alpha) + (atr[i-1] * (1.0 - alpha))
        
    return atr

@njit(cache=True)
def calculate_adx_njit(high_arr, low_arr, close_arr, window):
    """
    Piece 10: Standardized Vectorized ADX (Council Authority).
    Ultra-fast directional movement index logic.
    """
    n = len(high_arr)
    if n < (window * 2) + 1:
        return np.zeros(n)
        
    plus_dm = np.zeros(n)
    minus_dm = np.zeros(n)
    tr = np.zeros(n)
    
    for i in range(1, n):
        up_move = high_arr[i] - high_arr[i-1]
        down_move = low_arr[i-1] - low_arr[i]
        
        if up_move > down_move and up_move > 0:
            plus_dm[i] = up_move
        if down_move > up_move and down_move > 0:
            minus_dm[i] = down_move
            
        h_l = high_arr[i] - low_arr[i]
        h_pc = np.abs(high_arr[i] - close_arr[i-1])
        l_pc = np.abs(low_arr[i] - close_arr[i-1])
        tr[i] = max(h_l, max(h_pc, l_pc))

    # Wilders smoothing for DM and TR
    alpha = 1.0 / window
    s_plus_dm = np.zeros(n)
    s_minus_dm = np.zeros(n)
    s_tr = np.zeros(n)
    
    s_plus_dm[window] = np.sum(plus_dm[1:window+1])
    s_minus_dm[window] = np.sum(minus_dm[1:window+1])
    s_tr[window] = np.sum(tr[1:window+1])
    
    for i in range(window + 1, n):
        s_plus_dm[i] = s_plus_dm[i-1] - (s_plus_dm[i-1] / window) + plus_dm[i]
        s_minus_dm[i] = s_minus_dm[i-1] - (s_minus_dm[i-1] / window) + minus_dm[i]
        s_tr[i] = s_tr[i-1] - (s_tr[i-1] / window) + tr[i]
        
    plus_di = 100.0 * s_plus_dm / (s_tr + 1e-9)
    minus_di = 100.0 * s_minus_dm / (s_tr + 1e-9)
    
    dx = 100.0 * np.abs(plus_di - minus_di) / (plus_di + minus_di + 1e-9)
    adx = np.zeros(n)
    adx[window*2] = np.mean(dx[window+1:(window*2)+1])
    
    for i in range((window*2) + 1, n):
        adx[i] = (adx[i-1] * (window - 1) + dx[i]) / window
        
    return adx

@njit(cache=True)
def calculate_vwap_njit(close_arr, vol_arr):
    """Piece 10: Standardized VWAP Kernel (Council Authority)."""
    return np.cumsum(close_arr * vol_arr) / (np.cumsum(vol_arr) + 1e-9)

@njit(cache=True)
def calculate_approx_fitness_njit(risk_tilt, council_balance, stop_distance_atr):
    """
    Piece 12: Centralized Approx Fitness Kernel.
    Consolidated from OptimizerV2 to Council authority.
    """
    penalty = min(stop_distance_atr * 0.03, 0.30)
    score = (0.55 * risk_tilt) + (0.35 * council_balance) - penalty
    if score < 0.0: return 0.0
    if score > 1.0: return 1.0
    return score
