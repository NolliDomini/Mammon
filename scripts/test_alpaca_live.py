import runpy
from scripts.tools.test_alpaca_live import *  # noqa: F401,F403
if __name__ == "__main__":
    runpy.run_module("scripts.tools.test_alpaca_live", run_name="__main__")
