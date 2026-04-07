import runpy
from scripts.tools.rotate_backtest import *  # noqa: F401,F403
if __name__ == "__main__":
    runpy.run_module("scripts.tools.rotate_backtest", run_name="__main__")
