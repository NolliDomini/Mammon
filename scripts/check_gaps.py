import runpy
from scripts.tools.check_gaps import *  # noqa: F401,F403
if __name__ == "__main__":
    runpy.run_module("scripts.tools.check_gaps", run_name="__main__")
