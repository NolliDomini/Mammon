import sys
from pathlib import Path

# Ensure Mammon root is on path
MAMMON_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(MAMMON_ROOT))

try:
    from Thalamus.relay import Thalamus
    print("✅ Thalamus import success")
    
    # Attempt init without keys (should pass, clients just won't work)
    thal = Thalamus()
    print("✅ Thalamus initialization success")
    
    # Check for new methods
    if hasattr(thal, 'get_snapshot') and hasattr(thal, 'get_latest_bar'):
        print("✅ New sensory organs (get_snapshot, get_latest_bar) detected")
    else:
        print("❌ Missing new sensory organs")
        
except Exception as e:
    print(f"❌ Surgery Failure: {e}")
    import traceback
    traceback.print_exc()
