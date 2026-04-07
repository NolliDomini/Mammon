import runpy
from scripts.tools.fix_data import *  # noqa: F401,F403
if __name__ == "__main__":
    runpy.run_module("scripts.tools.fix_data", run_name="__main__")
