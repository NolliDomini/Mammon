import runpy
from scripts.tools.isolated_optimizer_test import *  # noqa: F401,F403
if __name__ == "__main__":
    runpy.run_module("scripts.tools.isolated_optimizer_test", run_name="__main__")
