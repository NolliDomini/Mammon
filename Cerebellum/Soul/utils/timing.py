from typing import List

def enforce_pulse_gate(pulse_type: str, allowed_pulses: List[str], lobe_name: str) -> bool:
    """
    Piece 14: Timing Invariant Enforcement.
    Ensures a lobe only processes pulses within its assigned window.
    
    Returns:
        bool: True if allowed, raises ValueError or returns False if inhibited.
    """
    pulse_u = str(pulse_type).upper()
    if pulse_u not in allowed_pulses:
        # In strictly enforced mode, we could raise an error.
        # For now, we log and inhibit to prevent state corruption.
        print(f"[TIMING_INHIBIT] Lobe '{lobe_name}' rejected pulse '{pulse_u}'. Allowed: {allowed_pulses}")
        return False
    return True
