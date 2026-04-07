import runpy
from scripts.tools.verify_mean_dev_kill import *  # noqa: F401,F403
if __name__ == "__main__":
    runpy.run_module("scripts.tools.verify_mean_dev_kill", run_name="__main__")
